import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from translate import Cache, MyMemoryTranslator, OpenAITranslator, TranslationError, Translator, _utf8_chunks
from pipeline import parse_translation_routes


class Response:
    def __init__(self, data): self.data = data
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self): return json.dumps(self.data).encode()


class ReliabilityTests(unittest.TestCase):
    def test_mymemory_splits_utf8_bytes_without_losing_text(self):
        source = "Rust 🦀 中文 ‘引用’ " * 70
        chunks = _utf8_chunks(source)
        self.assertEqual("".join(chunks), source)
        self.assertTrue(all(len(chunk.encode()) <= 500 for chunk in chunks))
        client = MyMemoryTranslator()
        with patch.object(client, "_translate_chunk", side_effect=lambda text: text) as call:
            self.assertEqual(client.translate_one(source), source)
        self.assertEqual(call.call_count, len(chunks))

    @patch("urllib.request.urlopen")
    def test_quota_exhaustion_is_a_permanent_failure_for_this_run(self, urlopen):
        urlopen.return_value = Response({"responseStatus": 200, "quotaFinished": True})
        with self.assertRaises(TranslationError) as error:
            MyMemoryTranslator().translate_one("hello")
        self.assertTrue(error.exception.permanent)

    @patch.object(Translator, "_probe")
    def test_partial_translation_is_not_cached_and_protected_code_is_unchanged(self, _probe):
        with tempfile.TemporaryDirectory() as directory:
            client = Translator(Cache(str(Path(directory) / "cache.json")), "mymemory")
            with patch.object(client, "_translate_seg", side_effect=["已翻译", "second"]):
                # Simulate a failed segment after an earlier successful segment.
                def translate(segment):
                    if segment.strip() == "first": return "已翻译"
                    client.stats["failed"] += 1
                    return segment
                with patch.object(client, "_translate_seg", side_effect=translate):
                    result = client.translate("first `這生存期` second", cache_key=1)
            self.assertIn("`這生存期`", result)
            self.assertIsNone(client.cache.get(1))

    @patch.object(Translator, "_probe")
    def test_transient_failure_waits_then_retries_same_segment(self, _probe):
        with tempfile.TemporaryDirectory() as directory:
            client = Translator(Cache(str(Path(directory) / "cache.json")), "mymemory")
            clock = [100.0]
            with patch("translate.time.time", side_effect=lambda: clock[0]), patch(
                "translate.time.sleep", side_effect=lambda seconds: clock.__setitem__(0, clock[0] + seconds)
            ), patch.object(client.backends[0], "translate_one", side_effect=[TranslationError("temporary"), "译文"]):
                self.assertEqual(client.translate("source", cache_key=2), "译文")
                self.assertGreaterEqual(clock[0], 115)
                self.assertEqual(client.stats["failed"], 0)
                self.assertEqual(client.cache.get(2), "译文")

    @patch.dict(os.environ, {"OPENAI_API_KEY": "test-key", "OPENAI_MODEL": "test-model"})
    @patch("translate.time.sleep")
    @patch("urllib.request.urlopen")
    def test_ai_honors_retry_after_and_does_not_log_response_body(self, urlopen, sleep):
        urlopen.side_effect = [
            urllib.error.HTTPError("https://example.test", 429, "rate", {"Retry-After": "7"}, io.BytesIO(b"private")),
            Response({"choices": [{"message": {"content": "译文"}}]}),
        ]
        self.assertEqual(OpenAITranslator().translate_one("source"), "译文")
        sleep.assert_called_once_with(7)

    def test_global_backend_can_override_default_channels(self):
        self.assertEqual(parse_translation_routes("", "openai")["t-libs"], "openai")
        self.assertEqual(parse_translation_routes("t-libs=mymemory", "openai")["t-libs"], "mymemory")


if __name__ == "__main__": unittest.main()
