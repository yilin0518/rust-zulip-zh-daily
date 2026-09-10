import json
import os
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from summarize import Summarizer, SummaryCache  # noqa: E402
from translate import OpenAITranslator  # noqa: E402


class FakeResponse:
    def __init__(self, text):
        self.body = json.dumps({"choices": [{"message": {"content": text}}]}).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.body


class OpenAICompatibleTests(unittest.TestCase):
    @patch.dict(os.environ, {
        "OPENAI_API_KEY": "test-key",
        "OPENAI_MODEL": "test-model",
        "OPENAI_BASE_URL": "https://example.test/v1/",
    }, clear=False)
    @patch("urllib.request.urlopen")
    def test_openai_compatible_request(self, urlopen):
        urlopen.return_value = FakeResponse("译文")
        client = OpenAITranslator()
        self.assertEqual(client.translate_one("text"), "译文")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://example.test/v1/chat/completions")
        payload = json.loads(request.data)
        self.assertEqual(payload["model"], "test-model")

    @patch.dict(os.environ, {
        "OPENAI_API_KEY": "test-key",
        "OPENAI_MODEL": "test-model",
    }, clear=False)
    def test_summary_uses_all_messages_and_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            summarizer = Summarizer(SummaryCache(os.path.join(directory, "cache.json")))
            prompts = []
            messages = [
                {"sender_full_name": "Alice", "content": "first message"},
                {"sender_full_name": "Bob", "content": "last message"},
            ]
            with patch.object(OpenAITranslator, "complete",
                              side_effect=lambda messages: prompts.append(messages) or "- 总结"):
                self.assertEqual(summarizer.summarize("general", "topic", messages), "- 总结")
                user_prompt = prompts[0][1]["content"]
                self.assertIn("first message", user_prompt)
                self.assertIn("last message", user_prompt)
                self.assertEqual(summarizer.summarize("general", "topic", messages), "- 总结")
                self.assertEqual(len(prompts), 1)

    @patch.dict(os.environ, {
        "OPENAI_API_KEY": "test-key",
        "OPENAI_MODEL": "test-model",
    }, clear=False)
    def test_concurrent_summaries_keep_topic_results_separate(self):
        active = 0
        peak = 0
        lock = threading.Lock()

        def complete(messages):
            nonlocal active, peak
            prompt = messages[1]["content"]
            topic = prompt.splitlines()[0].removeprefix("话题：")
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.02 if topic == "slow" else 0.005)
            with lock:
                active -= 1
            return "- " + topic

        with tempfile.TemporaryDirectory() as directory:
            summarizer = Summarizer(SummaryCache(os.path.join(directory, "cache.json")))
            topics = ("slow", "fast", "middle")
            with patch.object(OpenAITranslator, "complete", side_effect=complete):
                from concurrent.futures import ThreadPoolExecutor, as_completed
                with ThreadPoolExecutor(max_workers=3) as executor:
                    futures = {
                        executor.submit(summarizer.summarize, "general", topic, [
                            {"sender_full_name": "Alice", "content": topic + " message"},
                        ]): topic
                        for topic in topics
                    }
                    results = {futures[future]: future.result()
                               for future in as_completed(futures)}

            self.assertGreater(peak, 1)
            self.assertEqual(results, {topic: "- " + topic for topic in topics})


if __name__ == "__main__":
    unittest.main()
