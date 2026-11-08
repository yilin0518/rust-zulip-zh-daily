import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts"))
from site_data import write_site_data


class SiteDataTests(unittest.TestCase):
    def test_catalog_is_small_and_details_are_stable_and_complete(self):
        messages = [
            {"id": 12, "time": 20, "en": "new", "zh": "新消息", "sender": "B"},
            {"id": 10, "time": 10, "en": "old", "zh": "旧消息", "sender": "A"},
        ]
        streams = [{"stream": "t-libs", "display": "T-libs", "topics": [{
            "name": "../../带空格的 topic / 🦀", "name_zh": "示例话题", "summary": "- 摘要",
            "count": 99, "first": 0, "last": 0, "messages": messages,
        }]}]
        with tempfile.TemporaryDirectory() as directory:
            meta = write_site_data(streams, directory, sample=True)
            self.assertTrue(meta["sample"])
            self.assertEqual(meta["schema_version"], 2)
            with open(os.path.join(directory, meta["streams"][0]["file"]), encoding="utf-8") as f:
                topic = json.load(f)["topics"][0]
            self.assertNotIn("messages", topic)
            self.assertEqual(topic["count"], 2)
            self.assertEqual((topic["first"], topic["last"], topic["last_id"]), (10, 20, 12))
            self.assertRegex(topic["file"], r"^topics/[a-f0-9]{24}\.json$")
            with open(os.path.join(directory, topic["file"]), encoding="utf-8") as f:
                detail = json.load(f)
            self.assertEqual([m["id"] for m in detail["messages"]], [10, 12])
            streams[0]["topics"][0]["messages"].append(
                {"id": 15, "time": 30, "en": "latest", "zh": "最新", "sender": "C"})
            next_meta = write_site_data(streams, directory)
            with open(os.path.join(directory, next_meta["streams"][0]["file"]), encoding="utf-8") as f:
                updated = json.load(f)["topics"][0]
            self.assertEqual(topic["id"], updated["id"])
            self.assertEqual(updated["last_id"], 15)

    def test_empty_channel_exports_valid_catalog(self):
        with tempfile.TemporaryDirectory() as directory:
            meta = write_site_data([{"stream": "general", "display": "general", "topics": []}], directory)
            self.assertEqual(meta["streams"][0]["messages"], 0)
            with open(os.path.join(directory, "meta.json"), encoding="utf-8") as f:
                self.assertEqual(json.load(f), meta)


if __name__ == "__main__":
    unittest.main()
