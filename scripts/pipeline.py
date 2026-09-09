#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""每日管线：拉取 rust-lang Zulip 指定频道最新话题 → 翻译为中文 → 生成 site/data/*.json。

用法：
    python scripts/pipeline.py
环境变量：
    ZULIP_EMAIL / ZULIP_API_KEY   必填，Zulip bot 凭据
    TOPICS_PER_STREAM             每个频道最新话题数，默认 20
    STREAMS                       可选，逗号分隔的频道名，默认 general,t-compiler,t-libs,t-opsem
    TRANSLATE_BACKEND 等          见 translate.py
输出：
    site/data/<频道>.json         站点数据（双语）
    site/data/meta.json           元信息
    data/translation_cache.json   翻译缓存（需提交到仓库，避免重复翻译）
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from translate import Cache, Translator  # noqa: E402
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


def main():
    email = os.environ.get("ZULIP_EMAIL", "").strip()
    api_key = os.environ.get("ZULIP_API_KEY", "").strip()
    if not email or not api_key:
        sys.exit("错误：缺少环境变量 ZULIP_EMAIL / ZULIP_API_KEY（请用 Zulip bot 凭据，见 README）")

    topics_env = os.environ.get("TOPICS_PER_STREAM", "").strip()
    limit = int(topics_env) if topics_env else 20
    streams_cfg = DEFAULT_STREAMS
    if os.environ.get("STREAMS"):
        streams_cfg = [{"key": s.strip(), "display": s.strip().title()}
                       for s in os.environ["STREAMS"].split(",") if s.strip()]

    client = ZulipClient(email, api_key)
    cache = Cache()
    tr = Translator(cache)

    print("正在获取频道列表…")
    stream_ids = client.get_streams()
    os.makedirs(SITE_DATA, exist_ok=True)

    meta = {
        "last_updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "streams": [],
    }
    total_topics = total_msgs = 0

    for cfg in streams_cfg:
        name = cfg["key"]
        sid = stream_ids.get(name)
        if sid is None:
            print("[warn] 频道不存在，跳过: %s" % name)
            continue
        topics = client.get_latest_topics(sid, limit=limit)
        out_topics = []
        for t in topics:
            msgs = client.get_topic_messages(sid, t["name"])
            out_msgs = []
            for m in msgs:
                en = (m.get("content") or "").strip()
                if not en:
                    continue
                zh = tr.translate(en, cache_key=m["id"])
                out_msgs.append({
                    "id": m["id"],
                    "sender": m.get("sender_full_name") or "unknown",
                    "time": m.get("timestamp"),
                    "en": en,
                    "zh": zh,
                })
            title_zh = tr.translate(t["name"], cache_key="t|%s|%s" % (name, t["name"]))
            out_topics.append({
                "name": t["name"],
                "name_zh": title_zh,
                "count": len(out_msgs),
                "first": t["first"],
                "last": t["last"],
                "messages": out_msgs,
            })

        stream_data = {"stream": name, "display": cfg["display"], "topics": out_topics}
        with open(os.path.join(SITE_DATA, name + ".json"), "w", encoding="utf-8") as f:
            json.dump(stream_data, f, ensure_ascii=False)
        msg_count = sum(x["count"] for x in out_topics)
        meta["streams"].append({
            "key": name, "display": cfg["display"], "file": name + ".json",
            "topics": len(out_topics), "messages": msg_count,
        })
        total_topics += len(out_topics)
        total_msgs += msg_count
        print("[ok] %s: %d 个话题, %d 条消息" % (name, len(out_topics), msg_count))

    with open(os.path.join(SITE_DATA, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False)
    cache.save()

    print("\n完成：%d 个频道, %d 个话题, %d 条消息" % (len(streams_cfg), total_topics, total_msgs))
    print("翻译后端: %s  翻译字符数: %d  失败保留原文: %d" % (
        tr.stats["backend"], tr.stats["chars"], tr.stats["failed"]))
    print("站点数据已写入 %s" % SITE_DATA)


if __name__ == "__main__":
    main()
