"""Export a small catalog and lazily loaded topic detail files for the reader."""
import hashlib
import json
import os
import time


def write_site_data(streams, output_dir, updated_at=None, sample=False):
    os.makedirs(os.path.join(output_dir, "topics"), exist_ok=True)
    meta = {
        "schema_version": 2,
        "sample": sample,
        "last_updated": updated_at or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "streams": [],
    }

    def write(filename, value):
        with open(os.path.join(output_dir, filename), "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False)

    for stream in streams:
        key = stream["stream"]
        catalog = []
        for source in stream["topics"]:
            messages = sorted(source.get("messages", []), key=lambda m: (m["time"], m["id"]))
            # Names can contain slashes, emoji or traversal strings. Never use them as paths.
            identity = json.dumps([key, source["name"]], ensure_ascii=False)
            topic_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
            detail = dict(source, id=topic_id, stream=key, messages=messages,
                          count=len(messages), file="topics/%s.json" % topic_id)
            if messages:
                detail["first"] = messages[0]["time"]
                detail["last"] = messages[-1]["time"]
                detail["last_id"] = max(m["id"] for m in messages)
            write(detail["file"], detail)
            catalog.append({k: v for k, v in detail.items() if k != "messages"})
        catalog.sort(key=lambda topic: topic.get("last", 0), reverse=True)
        filename = "stream-%s.json" % hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
        write(filename, {"stream": key, "display": stream["display"], "topics": catalog})
        meta["streams"].append({
            "key": key, "display": stream["display"], "file": filename,
            "topics": len(catalog), "messages": sum(topic["count"] for topic in catalog),
        })
    # Write the entry point last, after every referenced file exists.
    write("meta.json", meta)
    return meta
