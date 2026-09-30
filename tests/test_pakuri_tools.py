import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from pakuri_tools import load_activity


class PakuriIntegrationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "data").mkdir()
        self.now = dt.datetime.now(dt.timezone.utc)

    def tearDown(self):
        self.temp.cleanup()

    def write(self, items, generated=None):
        (self.root / "data" / "latest.json").write_text(json.dumps({
            "schema_version": 1, "generated_at": (generated or self.now).isoformat(),
            "status": "ok", "items": items, "errors": [], "coverage": [],
        }), encoding="utf-8")

    def item(self, identifier, days=0, baseline=False, url=None):
        return {"id": identifier, "published_at": (self.now - dt.timedelta(days=days)).isoformat(),
                "url": url or f"https://github.com/lh3/test/commit/{identifier}", "baseline": baseline}

    async def test_cache_filters_old_future_and_untrusted_links(self):
        self.write([self.item("baseline", baseline=True), self.item("new"),
                    self.item("old", 3), self.item("future", -1),
                    self.item("external", url="https://example.org/"), {"id": "undated"}])
        with patch("pakuri_tools.asyncio.create_subprocess_exec", new_callable=AsyncMock) as run:
            result = await load_activity(self.root, days=1)
            run.assert_not_called()
        self.assertEqual([x["id"] for x in result["items"]], ["new", "baseline"])

    async def test_missing_collector_reports_unavailable(self):
        result = await load_activity(self.root)
        self.assertEqual(result["status"], "unavailable")

    async def test_failed_refresh_preserves_old_evidence_but_marks_stale(self):
        (self.root / "pakuri").mkdir()
        (self.root / "pakuri" / "__main__.py").write_text("", encoding="utf-8")
        (self.root / "targets.json").write_text("{}", encoding="utf-8")
        self.write([self.item("older")], self.now - dt.timedelta(hours=2))
        process = AsyncMock()
        process.wait.return_value = 1
        with patch("pakuri_tools.asyncio.create_subprocess_exec", return_value=process):
            result = await load_activity(self.root)
        self.assertEqual(result["status"], "stale")
        self.assertEqual(result["items"][0]["id"], "older")

    async def test_invalid_digest_does_not_trigger_arbitrary_execution(self):
        (self.root / "data" / "latest.json").write_text("[]", encoding="utf-8")
        with patch("pakuri_tools.asyncio.create_subprocess_exec", new_callable=AsyncMock) as run:
            result = await load_activity(self.root)
            run.assert_not_called()
        self.assertEqual(result["status"], "unavailable")
