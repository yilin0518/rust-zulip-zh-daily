#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""使用 OpenAI 兼容接口总结一个 Zulip 话题，并缓存结果。"""
import hashlib
import json
import os
import threading

from translate import OpenAITranslator, TranslationError

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SUMMARY_CACHE_PATH = os.path.join(ROOT, "data", "summary_cache.json")


class SummaryCache:
    def __init__(self, path=SUMMARY_CACHE_PATH):
        self.path = path
        self.data = {}
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    self.data = loaded
            except (OSError, ValueError):
                self.data = {}

    def get(self, key, digest):
        item = self.data.get(key)
        if isinstance(item, dict) and item.get("digest") == digest:
            return item.get("summary")
        return None

    def put(self, key, digest, summary, model):
        self.data[key] = {"digest": digest, "summary": summary, "model": model}

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False)
        os.replace(tmp, self.path)


class Summarizer:
    def __init__(self, cache=None):
        self.cache = cache or SummaryCache()
        # 启动时校验配置；每个工作线程使用自己的客户端。
        OpenAITranslator()
        self._local = threading.local()
        self._lock = threading.Lock()
        self.generated = 0
        self.failed = 0

    def _client(self):
        client = getattr(self._local, "client", None)
        if client is None:
            client = OpenAITranslator()
            self._local.client = client
        return client

    @staticmethod
    def _transcript(messages):
        parts = []
        for m in messages:
            sender = m.get("sender_full_name") or "unknown"
            content = (m.get("content") or "").strip()
            if content:
                parts.append("%s:\n%s" % (sender, content))
        return "\n\n---\n\n".join(parts)

    def summarize(self, stream, topic, messages):
        transcript = self._transcript(messages)
        if not transcript:
            return ""
        digest = hashlib.sha256(transcript.encode("utf-8")).hexdigest()
        key = "%s|%s" % (stream, topic)
        with self._lock:
            hit = self.cache.get(key, digest)
        if hit is not None:
            return hit
        prompt = (
            "话题：%s\n频道：%s\n\n以下是该话题按时间顺序排列的全部英文聊天原文。"
            "请用简体中文总结讨论的主要内容，准确保留 Rust 技术术语。总结应包括："
            "核心问题、重要观点或方案、已达成的结论，以及仍未解决的问题。"
            "如果某项不存在就省略。控制在 3 至 6 个简洁要点内，不要杜撰。\n\n%s"
            % (topic, stream, transcript)
        )
        try:
            client = self._client()
            summary = client.complete([
                {"role": "system", "content": (
                    "你是 Rust 技术社区讨论总结助手。只依据用户提供的完整聊天记录进行总结，"
                    "输出简体中文 Markdown 列表，不添加聊天记录中不存在的信息。")},
                {"role": "user", "content": prompt},
            ])
        except TranslationError as e:
            with self._lock:
                self.failed += 1
            print("[warn] AI 总结失败 %s/%s: %s" % (stream, topic, e), flush=True)
            return ""
        with self._lock:
            self.generated += 1
            self.cache.put(key, digest, summary, client.model)
        return summary
