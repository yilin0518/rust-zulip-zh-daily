import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from manual_update import apply_results, collect_tasks, summary_task
from summarize import SummaryCache
from translate import Cache
from update_report import build_report
from zulip_client import PublicZulipClient, ZulipClient


class ManualUpdateTests(unittest.TestCase):
    def streams(self):
        return [{"stream": "t-libs", "display": "T-libs", "topics": [{
            "name": "Size optimization", "summary": "", "messages": [{
                "id": 42, "sender": "Alice", "time": 1, "en": "Use `memcpy` safely.", "zh": "",
            }],
        }]}]

    def test_reviewed_local_results_complete_the_report_without_api_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Cache(str(Path(directory) / "cache.json"))
            summaries = SummaryCache(str(Path(directory) / "summaries.json"))
            streams = self.streams()
            sources, tasks = collect_tasks(streams, cache, summaries)
            self.assertEqual(len(sources), 2)
            task = summary_task("t-libs", streams[0]["topics"][0])
            apply_results({"42": "安全使用 `memcpy`。", "t|t-libs|Size optimization": "体积优化"},
                          {task["key"]: {"digest": task["digest"], "summary": "- 讨论安全使用 memcpy。"}},
                          streams, cache, summaries)
            streams[0]["topics"][0]["summary"] = "- 讨论安全使用 memcpy。"
            self.assertTrue(build_report(streams, cache)["complete"])
            self.assertEqual(collect_tasks(streams, cache, summaries)[1], [])

    def test_invalid_results_are_rejected_before_either_cache_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Cache(str(Path(directory) / "cache.json"))
            summaries = SummaryCache(str(Path(directory) / "summaries.json"))
            streams = self.streams()
            with self.assertRaises(ValueError):
                apply_results({"42": "丢失了代码。"}, {}, streams, cache, summaries)
            with self.assertRaises(ValueError):
                apply_results({"42": "使用 `memcpy`。"}, {"t-libs|Size optimization": {"digest": "stale", "summary": "旧摘要"}}, streams, cache, summaries)
            self.assertEqual(cache.data, {})
            self.assertEqual(summaries.data, {})

    def test_public_client_always_limits_queries_to_web_public_channels(self):
        with patch.object(ZulipClient, "_request", return_value={"messages": []}) as request:
            client = PublicZulipClient(["t-libs"])
            self.assertEqual(client.get_streams(), {"t-libs": "t-libs"})
            client.get_topic_messages("t-libs", "size")
            params = request.call_args.args[1]
            self.assertIn({"operator": "streams", "operand": "web-public"}, json.loads(params["narrow"]))
            self.assertEqual(params["anchor"], "newest")
            self.assertEqual(params["num_before"], 1000)
            self.assertEqual(params["include_anchor"], "false")

    def test_latest_messages_are_sorted_and_pagination_does_not_repeat_anchor(self):
        client = PublicZulipClient(["t-libs"])
        with patch.object(client, "_request", side_effect=[
            {"messages": [{"id": i} for i in range(501, 1501)]},
            {"messages": [{"id": i} for i in range(1, 501)]},
        ]) as request, patch("zulip_client.time.sleep"):
            messages = client.get_topic_messages("t-libs", "size", max_msgs=1500)
        self.assertEqual(messages[0]["id"], 1)
        self.assertEqual(messages[-1]["id"], 1500)
        self.assertEqual(request.call_args_list[1].args[1]["anchor"], "501")


if __name__ == "__main__": unittest.main()
