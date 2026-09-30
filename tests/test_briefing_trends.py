import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from briefing_trends import prepare_trends, record_delivery


class DeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_posted_links_are_consumed_and_queries_are_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            news = {"items": [{"url": "https://example.org/a"}, {"url": "https://example.org/b"}]}
            with patch("briefing_trends.collect_ai_news", new=AsyncMock(return_value=news)):
                groups, offered = await prepare_trends(SimpleNamespace(pakuri_path=""), state)
                self.assertFalse(state.exists())
                self.assertEqual(len(groups["ai"]["items"]), 2)
                record_delivery(offered, "소식 https://example.org/a", state)
                groups, _ = await prepare_trends(SimpleNamespace(pakuri_path=""), state)
            self.assertEqual(groups["ai"]["items"], [{"url": "https://example.org/b"}])
            self.assertEqual(len(json.loads(state.read_text(encoding="utf-8"))), 1)

    async def test_news_failure_is_reported_without_consuming_delivery_state(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            with patch("briefing_trends.collect_ai_news", new=AsyncMock(side_effect=RuntimeError("offline"))):
                groups, offered = await prepare_trends(SimpleNamespace(pakuri_path="configured"), state)
            self.assertEqual(groups["ai"]["status"], "unavailable")
            self.assertEqual(offered, [])
            self.assertFalse(state.exists())

    async def test_manual_briefing_keeps_previously_delivered_news_available(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            url = "https://example.org/a"
            record_delivery([{"key": "ai:" + url, "url": url}], url, state)
            before = state.read_bytes()
            with patch("briefing_trends.collect_ai_news", new=AsyncMock(return_value={"items": [{"url": url}]})):
                groups, _ = await prepare_trends(None, state, include_delivered=True)
            self.assertEqual(groups["ai"]["items"], [{"url": url}])
            self.assertEqual(before, state.read_bytes())

    def test_only_exact_url_tokens_are_acknowledged(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            url = "https://example.org/gpt-6"
            for text in (url + "-1", url + "?a=1", url + "#fragment",
                         "https://elsewhere.org/?next=" + url):
                record_delivery([{"key": "ai:short", "url": url}], text, state)
                self.assertNotIn("ai:short", json.loads(state.read_text(encoding="utf-8")))
            record_delivery([{"key": "ai:short", "url": url}], "<" + url + "|원문>", state)
            self.assertIn("ai:short", json.loads(state.read_text(encoding="utf-8")))
