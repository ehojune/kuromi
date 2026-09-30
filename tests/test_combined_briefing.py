import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from briefing_trends import deliver_briefing


class FakeSlack:
    def __init__(self, ok=True):
        self.ok = ok
        self.messages = []

    async def chat_postMessage(self, **message):
        self.messages.append(message)
        return {"ok": self.ok, "ts": "fixture", "message": {"text": message["text"]}}


class CombinedDeliveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "data").mkdir()
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        self.row = {"id": "commit:alice/demo:a", "kind": "commit", "title": "Update workflow",
                    "url": "https://github.com/alice/demo/commit/a", "published_at": now,
                    "observed_at": now, "actor": "alice", "repo": "alice/demo", "baseline": False,
                    "topics": ["workflows"], "relevance": ["example-project"]}
        (self.root / "data" / "latest.json").write_text(json.dumps({
            "schema_version": 1, "generated_at": now, "window_hours": 24, "status": "ok",
            "items": [self.row], "errors": [], "coverage": {},
        }), encoding="utf-8")
        self.state = self.root / "ai-state.json"
        self.text = "오늘 AI 동향: https://example.org/ai-update"
        self.offered = [{"key": "ai:update", "url": "https://example.org/ai-update"}]

    def tearDown(self):
        self.temp.cleanup()

    async def test_one_message_contains_news_and_pakuri_and_consumes_both_after_success(self):
        slack = FakeSlack()
        await deliver_briefing(slack, channel="fixture", text=self.text, offered=self.offered,
                               project_path=str(self.root), state_path=self.state)
        self.assertEqual(len(slack.messages), 1)
        self.assertIn(self.text, slack.messages[0]["text"])
        self.assertIn("*Pakuri 개발 활동*", slack.messages[0]["text"])
        self.assertIn(self.row["url"], slack.messages[0]["text"])
        self.assertIn("ai:update", json.loads(self.state.read_text(encoding="utf-8")))
        ledger = json.loads((self.root / "data" / "kuromi-delivery.json").read_text(encoding="utf-8"))
        self.assertIn(self.row["id"], ledger["delivered"])

    async def test_failed_send_does_not_consume_either_lane(self):
        with self.assertRaises(RuntimeError):
            await deliver_briefing(FakeSlack(False), channel="fixture", text=self.text,
                                   offered=self.offered, project_path=str(self.root), state_path=self.state)
        self.assertFalse(self.state.exists())
        self.assertFalse((self.root / "data" / "kuromi-delivery.json").exists())

    async def test_ai_ledger_write_failure_after_send_does_not_send_again_or_raise(self):
        slack = FakeSlack()
        with patch("briefing_trends.record_delivery", side_effect=OSError("fixture")):
            result = await deliver_briefing(slack, channel="fixture", text=self.text, offered=self.offered,
                                           project_path=str(self.root), state_path=self.state)
        self.assertTrue(result["ok"])
        self.assertEqual(len(slack.messages), 1)

    async def test_missing_pakuri_does_not_drop_news(self):
        slack = FakeSlack()
        await deliver_briefing(slack, channel="fixture", text=self.text, offered=self.offered,
                               project_path=str(self.root), state_path=self.state)
        (self.root / "data" / "latest.json").unlink()
        await deliver_briefing(slack, channel="fixture", text=self.text, offered=[],
                               project_path=str(self.root), state_path=self.state)
        self.assertIn(self.text, slack.messages[-1]["text"])
        self.assertIn("관측 결과를 읽지 못했습니다", slack.messages[-1]["text"])

    async def test_manual_briefing_reads_delivered_activity_and_keeps_both_ledgers(self):
        slack = FakeSlack()
        await deliver_briefing(slack, channel="fixture", text=self.text, offered=self.offered,
                               project_path=str(self.root), state_path=self.state)
        ledger = self.root / "data" / "kuromi-delivery.json"
        before = (ledger.read_bytes(), self.state.read_bytes())
        await deliver_briefing(slack, channel="fixture", text=self.text, offered=self.offered,
                               project_path=str(self.root), state_path=self.state,
                               thread_ts="thread-fixture", consume=False)
        self.assertIn(self.row["url"], slack.messages[-1]["text"])
        self.assertEqual(slack.messages[-1]["thread_ts"], "thread-fixture")
        self.assertEqual(before, (ledger.read_bytes(), self.state.read_bytes()))

    async def test_ai_link_in_pakuri_appendix_is_acknowledged_after_success(self):
        offered = [{"key": "ai:github-release", "url": self.row["url"]}]
        await deliver_briefing(FakeSlack(), channel="fixture", text="오늘 브리핑",
                               offered=offered, project_path=str(self.root), state_path=self.state)
        self.assertIn("ai:github-release", json.loads(self.state.read_text(encoding="utf-8")))
