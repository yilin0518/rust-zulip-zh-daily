#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""每日管线：拉取 Zulip 话题 → 翻译与 AI 总结 → 生成站点数据。

用法：
    python scripts/pipeline.py
环境变量：
    ZULIP_EMAIL / ZULIP_API_KEY   必填，Zulip bot 凭据
    TOPICS_PER_STREAM             每个频道最新话题数，默认 20
    STREAMS                       可选，逗号分隔的频道名，默认 general,t-compiler,t-libs,t-opsem
    OPENAI_API_KEY / OPENAI_MODEL 必填，翻译与总结共用
    OPENAI_BASE_URL               可选，第三方 OpenAI 兼容服务地址
    AI_CONCURRENCY                帖子总结并发数，默认 4
    STREAM_TRANSLATE_BACKENDS     按频道选择翻译后端，格式 stream=backend,...
输出：
    site/data/<频道>.json         站点数据（双语）
    site/data/meta.json           元信息
    data/translation_cache.json   翻译缓存（需提交到仓库，避免重复翻译）
    data/summary_cache.json       帖子总结缓存
"""
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from translate import Cache, Translator  # noqa: E402
from summarize import Summarizer  # noqa: E402
from zulip_client import ZulipClient  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE_DATA = os.path.join(ROOT, "site", "data")

DEFAULT_STREAMS = [
    {"key": "general", "display": "general"},
    {"key": "t-compiler", "display": "T-compiler"},
    {"key": "t-libs", "display": "T-libs"},
    {"key": "t-opsem", "display": "T-opsem"},
]

DEFAULT_TRANSLATION_ROUTES = {
    "general": "deepl",
    "t-compiler": "deepl",
    "t-libs": "baidu",
    "t-opsem": "baidu",
}
SUPPORTED_TRANSLATION_BACKENDS = {"openai", "deepl", "baidu", "google", "mymemory", "auto"}


def parse_translation_routes(raw):
    routes = dict(DEFAULT_TRANSLATION_ROUTES)
    if not raw:
        return routes
    for entry in raw.split(","):
        if not entry.strip():
            continue
        try:
            stream, backend = (part.strip() for part in entry.split("=", 1))
        except ValueError:
            raise ValueError("翻译路由格式错误: %s" % entry)
        backend = backend.lower()
        if not stream or backend not in SUPPORTED_TRANSLATION_BACKENDS:
            raise ValueError("无效翻译路由: %s" % entry)
        routes[stream] = backend
    return routes


def main():
    email = os.environ.get("ZULIP_EMAIL", "").strip()
    api_key = os.environ.get("ZULIP_API_KEY", "").strip()
    if not email or not api_key:
        sys.exit("错误：缺少环境变量 ZULIP_EMAIL / ZULIP_API_KEY（请用 Zulip bot 凭据，见 README）")

    topics_env = os.environ.get("TOPICS_PER_STREAM", "").strip()
    limit = int(topics_env) if topics_env else 20
    concurrency_env = os.environ.get("AI_CONCURRENCY", "").strip()
    summary_concurrency = int(concurrency_env) if concurrency_env else 4
    if summary_concurrency < 1:
        sys.exit("错误：AI_CONCURRENCY 必须是大于 0 的整数")
    budget_env = os.environ.get("TRANSLATE_BUDGET_MIN", "").strip()
    budget_min = float(budget_env) if budget_env else 50.0  # 翻译总时间预算（分钟）
    streams_cfg = DEFAULT_STREAMS
    if os.environ.get("STREAMS"):
        streams_cfg = [{"key": s.strip(), "display": s.strip().title()}
                       for s in os.environ["STREAMS"].split(",") if s.strip()]

    default_backend = (os.environ.get("TRANSLATE_BACKEND") or "openai").strip().lower()
    if default_backend not in SUPPORTED_TRANSLATION_BACKENDS:
        sys.exit("错误：无效翻译后端: %s" % default_backend)
    try:
        translation_routes = parse_translation_routes(
            os.environ.get("STREAM_TRANSLATE_BACKENDS", "").strip())
        stream_backends = {
            cfg["key"]: translation_routes.get(cfg["key"], default_backend)
            for cfg in streams_cfg
        }
    except ValueError as e:
        sys.exit("错误：%s" % e)

    client = ZulipClient(email, api_key)
    cache = Cache()
    try:
        translators = {
            backend: Translator(cache, backend=backend)
            for backend in sorted(set(stream_backends.values()))
        }
        summarizer = Summarizer()
    except Exception as e:
        sys.exit("错误：翻译后端初始化失败——%s" % e)

    t0 = time.time()

    def budget_exhausted():
        return (time.time() - t0) / 60.0 > budget_min

    print("正在获取频道列表…", flush=True)
    stream_ids = client.get_streams()
    os.makedirs(SITE_DATA, exist_ok=True)

    meta = {
        "last_updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "streams": [],
    }
    total_topics = total_msgs = 0
    stream_jobs = []
    summary_futures = {}

    print("AI 总结并发数: %d" % summary_concurrency, flush=True)
    with ThreadPoolExecutor(max_workers=summary_concurrency) as executor:
        # 第一阶段只拉取帖子并提交总结，让不同帖子的 AI 请求真正并发。
        for cfg in streams_cfg:
            name = cfg["key"]
            sid = stream_ids.get(name)
            if sid is None:
                print("[warn] 频道不存在，跳过: %s" % name)
                continue
            topics = client.get_latest_topics(sid, limit=limit)
            topic_jobs = []
            for ti, topic in enumerate(topics, 1):
                msgs = client.get_topic_messages(sid, topic["name"])
                job = {"topic": topic, "messages": msgs}
                future = executor.submit(summarizer.summarize, name, topic["name"], msgs)
                job["summary_future"] = future
                summary_futures[future] = (name, topic["name"], job)
                topic_jobs.append(job)
                print("[fetch] %s 话题 %d/%d: %s (%d 条) 已提交总结"
                      % (name, ti, len(topics), topic["name"][:50], len(msgs)), flush=True)
            stream_jobs.append({"name": name, "display": cfg["display"], "topics": topic_jobs})

        # 第二阶段保持翻译串行，避免翻译器共享状态和缓存发生竞争。
        stream_outputs = []
        for stream_job in stream_jobs:
            name = stream_job["name"]
            tr = translators[stream_backends[name]]
            out_topics = []
            for ti, job in enumerate(stream_job["topics"], 1):
                topic = job["topic"]
                msgs = job["messages"]
                pairs = []       # [(msg_id, en)] 待翻译
                msg_meta = {}    # msg_id -> 消息元数据
                for message in msgs:
                    en = (message.get("content") or "").strip()
                    if not en:
                        continue
                    md = {
                        "id": message["id"],
                        "sender": message.get("sender_full_name") or "unknown",
                        "time": message.get("timestamp"),
                        "en": en,
                    }
                    msg_meta[message["id"]] = md
                    if budget_exhausted():
                        md["zh"] = ""
                    else:
                        pairs.append((message["id"], en))
                zhs = tr.translate_batch(pairs) if pairs else {}
                out_msgs = []
                for mid, md in msg_meta.items():
                    md["zh"] = md.get("zh", zhs.get(mid, ""))
                    out_msgs.append(md)
                title_zh = tr.translate(topic["name"], cache_key="t|%s|%s" % (name, topic["name"]))
                out_topic = {
                    "name": topic["name"],
                    "name_zh": title_zh,
                    "summary": "",
                    "count": len(out_msgs),
                    "first": topic["first"],
                    "last": topic["last"],
                    "messages": out_msgs,
                }
                job["output"] = out_topic
                out_topics.append(out_topic)
                print("[progress] %s 话题 %d/%d: %s (%d 条) 翻译完成，已用 %.1f 分钟"
                      % (name, ti, len(stream_job["topics"]), topic["name"][:50], len(out_msgs),
                         (time.time() - t0) / 60.0), flush=True)
            stream_outputs.append({
                "name": name,
                "data": {"stream": name, "display": stream_job["display"], "topics": out_topics},
            })

        completed = 0
        for future in as_completed(summary_futures):
            name, topic_name, job = summary_futures[future]
            try:
                job["output"]["summary"] = future.result()
            except Exception as e:
                print("[warn] AI 总结任务异常 %s/%s: %s" % (name, topic_name, e), flush=True)
            completed += 1
            print("[summary] %d/%d: %s/%s" % (
                completed, len(summary_futures), name, topic_name[:50]), flush=True)

    for stream_output in stream_outputs:
        name = stream_output["name"]
        stream_data = stream_output["data"]
        out_topics = stream_data["topics"]
        with open(os.path.join(SITE_DATA, name + ".json"), "w", encoding="utf-8") as f:
            json.dump(stream_data, f, ensure_ascii=False)
        msg_count = sum(x["count"] for x in out_topics)
        meta["streams"].append({
            "key": name, "display": stream_data["display"], "file": name + ".json",
            "topics": len(out_topics), "messages": msg_count,
        })
        total_topics += len(out_topics)
        total_msgs += msg_count
        print("[ok] %s: %d 个话题, %d 条消息" % (name, len(out_topics), msg_count), flush=True)

    with open(os.path.join(SITE_DATA, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False)
    cache.save()
    summarizer.cache.save()

    print("\n完成：%d 个频道, %d 个话题, %d 条消息" % (len(streams_cfg), total_topics, total_msgs), flush=True)
    for backend, translator in translators.items():
        routed_streams = [name for name, selected in stream_backends.items() if selected == backend]
        print("翻译后端 %s (%s): %s  翻译字符数: %d  失败保留原文: %d" % (
            backend, ",".join(routed_streams), translator.stats["backend"],
            translator.stats["chars"], translator.stats["failed"]), flush=True)
    print("AI 总结: 新生成 %d，失败 %d" % (summarizer.generated, summarizer.failed), flush=True)
    if budget_exhausted():
        print("[warn] 翻译时间预算（%s 分钟）已耗尽，部分消息保留英文原文" % budget_min, flush=True)
    print("站点数据已写入 %s" % SITE_DATA, flush=True)


if __name__ == "__main__":
    main()
