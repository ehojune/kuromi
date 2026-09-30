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

    async def test_news_failure_does_not_drop_successful_github_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("briefing_trends.collect_ai_news", new=AsyncMock(side_effect=RuntimeError("offline"))), \
                 patch("briefing_trends.load_activity", new=AsyncMock(return_value={"items": [{"url": "https://github.com/a/b"}]})):
                groups, _ = await prepare_trends(SimpleNamespace(pakuri_path="configured"), Path(directory) / "state.json")
            self.assertEqual(groups["ai"]["status"], "unavailable")
            self.assertEqual(len(groups["github"]["items"]), 1)
