#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Zulip API 客户端：拉取频道、最新话题、话题全部消息。

rust-lang Zulip 的 API 需要登录（Basic Auth：邮箱 + API Key），
即使频道是公开的。请用个人账号创建的 bot 凭据（见 README）。
"""
import base64
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE = "https://rust-lang.zulipchat.com/api/v1"
UA = "rust-zulip-zh-daily/1.0"


class ZulipError(Exception):
    pass


class ZulipClient:
    def __init__(self, email, api_key):
        if not email or not api_key:
            raise ZulipError("缺少 ZULIP_EMAIL / ZULIP_API_KEY")
        token = base64.b64encode(("%s:%s" % (email, api_key)).encode("utf-8")).decode("ascii")
        self.headers = {"User-Agent": UA, "Authorization": "Basic " + token}

    def _request(self, path, params=None):
        url = BASE + path
        if params:
            url += "?" + urllib.parse.urlencode(params, doseq=True)
        last = None
        for attempt in range(4):
            try:
                req = urllib.request.Request(url, headers=self.headers)
                with urllib.request.urlopen(req, timeout=40) as r:
                    data = json.loads(r.read().decode("utf-8", "replace"))
                if data.get("result") == "error":
                    code = data.get("code", "")
                    if code == "RATE_LIMIT_HIT" and attempt < 3:
                        time.sleep(5 * (attempt + 1))
                        continue
                    raise ZulipError("Zulip API 错误: %s" % data.get("msg", code))
                return data
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503) and attempt < 3:
                    time.sleep(3 * (attempt + 1))
                    continue
                raise ZulipError("Zulip http %s" % e.code)
            except urllib.error.URLError as e:
                last = e
                if attempt < 3:
                    time.sleep(2)
                    continue
        raise ZulipError("Zulip 网络错误: %s" % last)

    def get_streams(self):
        data = self._request("/streams", {"include_public": "true"})
        return {s.get("name"): s.get("stream_id") for s in data.get("streams", []) if s.get("name")}

    def get_latest_topics(self, stream_id, limit=20, max_messages=1500):
        """返回该频道最新的 limit 个话题（按最后活跃时间倒序）。"""
        narrow = json.dumps([{"operator": "stream", "operand": stream_id}])
        collected = []
        anchor = "newest"
        while len(collected) < max_messages:
            params = {"anchor": anchor, "num_before": 1000,
                      "apply_markdown": "false", "narrow": narrow}
            msgs = self._request("/messages", params).get("messages", [])
            if not msgs:
                break
            collected.extend(msgs)
            if len(msgs) < 1000:
                break
            oldest = min(m["id"] for m in msgs)
            anchor = str(oldest - 1)
            time.sleep(0.15)
        topics = {}
        for m in collected[:max_messages]:
            subj = m.get("topic") or m.get("subject") or "(no topic)"
            t = topics.setdefault(subj, {
                "name": subj, "first": m["timestamp"], "last": m["timestamp"],
                "last_id": m["id"], "count": 0})
            t["count"] += 1
            if m["timestamp"] < t["first"]:
                t["first"] = m["timestamp"]
            if m["timestamp"] > t["last"]:
                t["last"] = m["timestamp"]
                t["last_id"] = m["id"]
        ordered = sorted(topics.values(), key=lambda t: (t["last"], t["last_id"]), reverse=True)
        return ordered[:limit]

    def get_topic_messages(self, stream_id, topic, max_msgs=1000):
        """返回某话题的全部消息（按时间正序），单话题最多 max_msgs 条。"""
        narrow = json.dumps([
            {"operator": "stream", "operand": stream_id},
            {"operator": "topic", "operand": topic},
        ])
        out = []
        anchor = "oldest"
        while len(out) < max_msgs:
            params = {"anchor": anchor, "num_after": 1000,
                      "apply_markdown": "false", "narrow": narrow}
            msgs = self._request("/messages", params).get("messages", [])
            if not msgs:
                break
            out.extend(msgs)
            if len(msgs) < 1000:
                break
            newest = max(m["id"] for m in msgs)
            anchor = str(newest + 1)
            time.sleep(0.15)
        return out[:max_msgs]
