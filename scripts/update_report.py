"""Report content completeness independently of the process exit status."""
import json
import os
import re

from translate import split_segments


def needs_translation(text):
    return any(not keep and re.search(r"[A-Za-z]{2,}", segment)
               for segment, keep in split_segments(text or ""))


def build_report(streams, cache):
    report = {"topics": 0, "messages": 0, "translated": 0, "pending": 0,
              "missing_titles": 0, "missing_summaries": 0, "pending_by_stream": {}}
    for stream in streams:
        pending = 0
        for topic in stream["topics"]:
            report["topics"] += 1
            if not topic.get("summary", "").strip():
                report["missing_summaries"] += 1
            title_key = "t|%s|%s" % (stream["stream"], topic["name"])
            if needs_translation(topic["name"]) and cache.get(title_key, topic["name"]) is None:
                report["missing_titles"] += 1
            for message in topic["messages"]:
                report["messages"] += 1
                if not needs_translation(message["en"]) or cache.get(message["id"], message["en"]) is not None:
                    report["translated"] += 1
                else:
                    report["pending"] += 1
                    pending += 1
        report["pending_by_stream"][stream["stream"]] = pending
    report["complete"] = not (report["pending"] or report["missing_titles"] or report["missing_summaries"])
    return report


def write_report(report, path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    summary = (
        "## Rust Zulip update\n\n"
        "| Result | Count |\n| --- | ---: |\n"
        "| Topics | {topics} |\n| Messages | {messages} |\n"
        "| Complete translations (including cache) | {translated} |\n"
        "| Pending message translations | {pending} |\n"
        "| Pending titles | {missing_titles} |\n| Missing summaries | {missing_summaries} |\n\n"
    ).format(**report)
    summary += ("Content is complete.\n" if report["complete"] else
                "Content is incomplete. Successful cache entries are retained for the next run.\n")
    for name, pending in report["pending_by_stream"].items():
        summary += "\n- %s: %d pending messages" % (name, pending)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as handle:
            handle.write(summary + "\n")
    print(summary, flush=True)
