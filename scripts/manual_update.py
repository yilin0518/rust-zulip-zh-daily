#!/usr/bin/env python3
"""Prepare local agent work, apply reviewed results, and publish a cache-only snapshot.

This workflow never calls a translation provider or an AI API.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import time
import urllib.parse
import urllib.request

from site_data import write_site_data
from summarize import SummaryCache, Summarizer
from translate import Cache, split_segments
from update_report import build_report, needs_translation, write_report
from zulip_client import PublicZulipClient, ZulipClient

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "work" / "update"
SNAPSHOT = ROOT / "data" / "site_snapshot.json"


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def summary_task(stream, topic):
    messages = [{"sender_full_name": m["sender"], "content": m["en"]} for m in topic["messages"]]
    transcript = Summarizer._transcript(messages)
    return {"key": "%s|%s" % (stream, topic["name"]),
            "digest": hashlib.sha256(transcript.encode("utf-8")).hexdigest(),
            "transcript": transcript}


def collect_tasks(streams, cache, summaries):
    translations, tasks = {}, []
    for stream in streams:
        for topic in stream["topics"]:
            pairs = [("t|%s|%s" % (stream["stream"], topic["name"]), topic["name"].strip())]
            pairs.extend((str(m["id"]), m["en"]) for m in topic["messages"])
            missing = []
            for key, source in pairs:
                if needs_translation(source) and cache.get(key, source) is None:
                    translations[key] = source
                    missing.append({"key": key, "source": source})
            summary = summary_task(stream["stream"], topic)
            pending_summary = summaries.get(summary["key"], summary["digest"]) is None
            if missing or pending_summary:
                tasks.append({"stream": stream["stream"], "topic": topic["name"],
                              "translations": missing,
                              "summary": summary if pending_summary else None})
    return translations, tasks


def prepare(args):
    streams = [name.strip() for name in args.streams.split(",") if name.strip()]
    if not streams or args.topics < 1:
        raise ValueError("Select at least one channel and a positive topic count")
    email, key = os.environ.get("ZULIP_EMAIL"), os.environ.get("ZULIP_API_KEY")
    client = ZulipClient(email, key) if email and key else PublicZulipClient(streams)
    ids = client.get_streams()
    output = []
    for name in streams:
        if name not in ids:
            raise ValueError("Channel not available: %s" % name)
        topics = []
        for topic in client.get_latest_topics(ids[name], limit=args.topics):
            messages = client.get_topic_messages(ids[name], topic["name"])
            mapped = [{"id": m["id"], "sender": m.get("sender_full_name", "unknown"),
                       "time": m["timestamp"], "en": m["content"].strip(), "zh": ""}
                      for m in messages if m.get("content", "").strip()]
            if not mapped:
                continue
            topics.append({"name": topic["name"], "name_zh": "", "summary": "",
                           "count": len(mapped), "first": mapped[0]["time"], "last": mapped[-1]["time"],
                           "zulip_url": "https://rust-lang.zulipchat.com/#narrow/with/%d" % mapped[-1]["id"],
                           "messages": mapped})
            print("Fetched %s / %s (%d messages)" % (name, topic["name"], len(mapped)), flush=True)
        output.append({"stream": name, "display": name, "topics": topics})
    write(WORK / "source.json", {"fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                 "streams": output})
    _, tasks = collect_tasks(output, Cache(), SummaryCache())
    entries = []
    for task in tasks:
        identity = hashlib.sha256((task["stream"] + "|" + task["topic"]).encode()).hexdigest()[:24]
        filename = "tasks/%s.json" % identity
        write(WORK / filename, task)
        entries.append({"file": filename, "stream": task["stream"], "topic": task["topic"],
                        "translations": len(task["translations"]), "summary": task["summary"] is not None})
    write(WORK / "manifest.json", entries)
    print("Prepared %d topic tasks, %d translations. See work/update/manifest.json" % (
        len(tasks), sum(len(task["translations"]) for task in tasks)))


def apply_results(translations, summary_results, streams, cache, summaries):
    sources = {}
    valid_summaries = {}
    for stream in streams:
        for topic in stream["topics"]:
            sources["t|%s|%s" % (stream["stream"], topic["name"])] = topic["name"].strip()
            sources.update({str(m["id"]): m["en"] for m in topic["messages"]})
            task = summary_task(stream["stream"], topic)
            valid_summaries[task["key"]] = task["digest"]
    # Validate the entire batch before changing either cache.
    for key, translated in translations.items():
        if key not in sources or not isinstance(translated, str) or not translated.strip():
            raise ValueError("Invalid translation key or empty result: %s" % key)
        for segment, keep in split_segments(sources[key]):
            if keep and segment not in translated:
                raise ValueError("Protected code/link was changed in translation %s" % key)
    for key, result in summary_results.items():
        if (key not in valid_summaries or not isinstance(result, dict)
                or result.get("digest") != valid_summaries[key]
                or not isinstance(result.get("summary"), str) or not result["summary"].strip()):
            raise ValueError("Summary is missing or does not match current source: %s" % key)
    for key, translated in translations.items():
        cache.put(key, sources[key], translated.strip(), "codex-local")
    for key, result in summary_results.items():
        summaries.put(key, result["digest"], result["summary"].strip(), "codex-local")


def apply(args):
    streams = read(WORK / "source.json")["streams"]
    translations = read(args.translations) if args.translations else {}
    summaries = read(args.summaries) if args.summaries else {}
    cache, summary_cache = Cache(), SummaryCache()
    apply_results(translations, summaries, streams, cache, summary_cache)
    cache.save()
    summary_cache.save()
    _, remaining = collect_tasks(streams, cache, summary_cache)
    print("Saved reviewed results; %d topics still have pending work" % len(remaining))


def finalize(_args):
    source = read(WORK / "source.json")
    cache, summaries = Cache(), SummaryCache()
    for stream in source["streams"]:
        for topic in stream["topics"]:
            title_key = "t|%s|%s" % (stream["stream"], topic["name"])
            topic["name_zh"] = cache.get(title_key, topic["name"].strip()) or topic["name"]
            task = summary_task(stream["stream"], topic)
            topic["summary"] = summaries.get(task["key"], task["digest"]) or ""
            for message in topic["messages"]:
                message["zh"] = cache.get(message["id"], message["en"]) or message["en"]
    report = build_report(source["streams"], cache)
    write_report(report, str(WORK / "report.json"))
    if not report["complete"]:
        raise ValueError("Pending work remains; no publishable snapshot was changed")
    source["quality"] = report
    write(SNAPSHOT, source)
    render_snapshot()
    print("Snapshot ready. Run tests and npm run build, then commit and push the reviewed files.")


def render_snapshot():
    snapshot = read(SNAPSHOT)
    if not snapshot.get("streams"):
        raise ValueError("Snapshot has no channels")
    write_site_data(snapshot["streams"], str(ROOT / "site" / "data"),
                    updated_at=snapshot["fetched_at"])


def import_published(args):
    """One-time migration: preserve currently published content without re-translating it."""
    base = args.url.rstrip("/") + "/data/"
    def fetch(filename):
        with urllib.request.urlopen(urllib.parse.urljoin(base, filename), timeout=40) as response:
            return json.load(response)
    meta = fetch("meta.json")
    if meta.get("sample"):
        raise ValueError("Refusing to import sample data as published content")
    streams = []
    for stream in meta["streams"]:
        data = fetch(stream["file"])
        for topic in data["topics"]:
            if "messages" not in topic:
                detail = fetch(topic["file"])
                topic.update(detail)
            if not topic.get("zulip_url") and topic.get("messages"):
                topic["zulip_url"] = "https://rust-lang.zulipchat.com/#narrow/with/%d" % topic["messages"][-1]["id"]
        streams.append(data)
    write(SNAPSHOT, {"fetched_at": meta["last_updated"], "streams": streams,
                     "imported_from": args.url, "quality": {"migrated": True,
                     "note": "Existing published translations preserved; not newly reviewed."}})
    render_snapshot()
    print("Preserved published snapshot:", meta["last_updated"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    fetch = commands.add_parser("prepare")
    fetch.add_argument("--streams", default="general,t-compiler,t-libs,t-opsem")
    fetch.add_argument("--topics", type=int, default=20)
    fetch.set_defaults(function=prepare)
    apply_command = commands.add_parser("apply")
    apply_command.add_argument("--translations")
    apply_command.add_argument("--summaries")
    apply_command.set_defaults(function=apply)
    commands.add_parser("finalize").set_defaults(function=finalize)
    commands.add_parser("render").set_defaults(function=lambda _: render_snapshot())
    bootstrap = commands.add_parser("import-published")
    bootstrap.add_argument("--url", default="https://yilin0518.github.io/rust-zulip-zh-daily/")
    bootstrap.set_defaults(function=import_published)
    args = parser.parse_args()
    args.function(args)


if __name__ == "__main__":
    main()
