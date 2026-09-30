from datetime import datetime, timedelta, timezone
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from pakuri_context import read_briefing_context, render_context
from pakuri_tools import post_briefing

NOW = datetime(2026, 10, 1, 0, tzinfo=timezone.utc)


def record(number, **changes):
    row = {"id": "commit:alice/demo:" + str(number), "kind": "commit", "title": "Improve analysis",
           "url": "https://github.com/alice/demo/commit/" + str(number), "repo": "alice/demo",
           "published_at": (NOW - timedelta(days=3)).isoformat(), "observed_at": NOW.isoformat(),
           "actor": "alice", "baseline": False, "topics": ["genomics"], "relevance": []}
    result = {**row, **changes}
    if "repo" in changes and "url" not in changes:
        result["url"] = "https://github.com/" + result["repo"] + "/commit/" + str(number)
    return result


class ContextTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "data").mkdir()
        self.people = [{"login": "alice", "name": "Alice Example", "topics": ["genomics"],
            "verification": {"status": "verified", "account_type": "User", "checked_at": "2026-10-01",
                "affiliation": {"status": "verified_primary_source", "current": "Example University, researcher",
                                "sources": ["https://example.edu/alice"]},
                "projects": [{"repository": "alice/demo", "relationship": "owner"}]}}]
        self.targets()
        with closing(sqlite3.connect(self.root / "data/state.sqlite3")) as db, db:
            db.execute("CREATE TABLE items (id TEXT PRIMARY KEY, body TEXT, published_at TEXT, observed_at TEXT)")
        self.rows([record(1)])

    def tearDown(self):
        self.temporary.cleanup()

    def targets(self):
        (self.root / "targets.json").write_text(json.dumps({"schema_version": 1, "people": self.people,
            "repositories": [{"full_name": "alice/demo", "topics": ["genomics"]}]}), encoding="utf-8")

    def rows(self, rows):
        with closing(sqlite3.connect(self.root / "data/state.sqlite3")) as db, db:
            db.execute("DELETE FROM items")
            db.executemany("INSERT INTO items VALUES (?,?,?,?)",
                [(r["id"], json.dumps(r), r["published_at"], r["observed_at"]) for r in rows])

    def read(self, **kwargs):
        return read_briefing_context(str(self.root), now=NOW, **kwargs)

    def test_fortnight_uses_publication_dates_and_distinct_repos_not_commit_volume(self):
        rows = [record(i) for i in range(100)]
        rows += [record("baseline", repo="bob/initial", topics=["agents"], baseline=True),
                 record("old", repo="bob/old", published_at=(NOW - timedelta(days=15)).isoformat()),
                 record("edge", repo="bob/edge", published_at=(NOW - timedelta(days=14)).isoformat()),
                 record("bad", url="https://github.com.evil/alice/demo")]
        self.rows(rows)
        context = self.read()
        history = context["two_week"]
        self.assertEqual(history["active_repositories"], 3)
        self.assertEqual(history["initial_records"], 1)
        self.assertEqual(history["rejected_items"], 1)
        self.assertEqual(history["status"], "partial")
        fields = {f["name"]: f["repositories"] for f in history["fields"]}
        self.assertEqual(fields["유전체·생물정보학"], 2)
        self.assertEqual(fields["AI 에이전트"], 1)

    def test_reads_never_change_database_roster_or_delivery_state(self):
        paths = [self.root / "data/state.sqlite3", self.root / "targets.json"]
        before = [hashlib.sha256(p.read_bytes()).hexdigest() for p in paths]
        self.read()
        self.read()
        self.assertEqual(before, [hashlib.sha256(p.read_bytes()).hexdigest() for p in paths])
        self.assertFalse((self.root / "data/kuromi-delivery.json").exists())

    def test_rotation_changes_only_at_korean_midnight(self):
        self.people.append({**self.people[0], "login": "bob", "name": "Bob"})
        self.targets()
        first = read_briefing_context(str(self.root), now=NOW.replace(hour=14, minute=59))
        next_day = read_briefing_context(str(self.root), now=NOW.replace(hour=15))
        repeated = read_briefing_context(str(self.root), now=NOW.replace(hour=16))
        self.assertNotEqual(first["spotlight"]["login"], next_day["spotlight"]["login"])
        self.assertEqual(next_day["spotlight"]["login"], repeated["spotlight"]["login"])
        self.assertEqual(next_day["spotlight"]["date"], "2026-10-02")

    def test_profile_has_identity_affiliation_work_and_actor_evidence(self):
        context = self.read()
        text = render_context(context)
        for expected in ("Alice Example", "유전체·생물정보학",
                         "Example University", "https://example.edu/alice", "alice/demo", "Improve analysis"):
            self.assertIn(expected, text)
        self.assertEqual(len(context["spotlight"]["recent_activity"]), 1)
        self.rows([record(1, actor="other-author")])
        self.assertEqual(self.read()["spotlight"]["recent_activity"], [])

    def test_project_push_is_reported_without_attributing_it_to_the_person(self):
        self.rows([record(1, actor="other-author")])
        with closing(sqlite3.connect(self.root / "data/state.sqlite3")) as db, db:
            db.execute("CREATE TABLE repositories (name TEXT PRIMARY KEY, body TEXT)")
            db.execute("INSERT INTO repositories VALUES (?,?)", ("alice/demo", json.dumps({
                "full_name": "alice/demo", "private": False,
                "pushed_at": (NOW - timedelta(days=1)).isoformat()})))
        context = self.read()
        self.assertEqual(context["spotlight"]["recent_activity"], [])
        self.assertEqual(len(context["spotlight"]["related_updates"]), 1)
        self.assertIn("본인 작업 여부 미확인", render_context(context))

    def test_self_report_is_marked_and_external_text_is_escaped(self):
        self.people[0]["name"] = "<!channel>"
        affiliation = self.people[0]["verification"]["affiliation"]
        affiliation.update(status="unconfirmed", self_reported="Example Labs <@UFAKE>", sources=["http://[bad"])
        self.targets()
        text = render_context(self.read())
        self.assertIn("소속 미검증", text)
        self.assertNotIn("<!channel>", text)
        self.assertNotIn("<@UFAKE>", text)
        self.assertIn("https://github.com/alice", text)

    def test_stale_collection_does_not_look_like_current_development(self):
        context = self.read(activity={"status": "stale"})
        self.assertEqual(context["two_week"]["status"], "stale")
        self.assertEqual(context["two_week"]["active_repositories"], 0)
        self.assertEqual(context["spotlight"]["recent_activity"], [])

    def test_missing_or_corrupt_history_keeps_profile_without_inventing_activity(self):
        (self.root / "data/state.sqlite3").unlink()
        context = self.read()
        self.assertEqual(context["two_week"]["status"], "missing")
        self.assertIn("Alice Example", render_context(context))
        (self.root / "data/state.sqlite3").write_bytes(b"corrupt")
        self.assertEqual(self.read()["two_week"]["status"], "invalid")


class EmptyDayDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_quiet_day_still_introduces_exactly_one_account_without_ledger_writes(self):
        fixture = ContextTests()
        fixture.setUp()
        try:
            (fixture.root / "data/latest.json").write_text(json.dumps({
                "schema_version": 1, "generated_at": NOW.isoformat(), "window_hours": 24,
                "status": "ok", "items": [], "coverage": {}, "errors": []}), encoding="utf-8")
            class Slack:
                def __init__(self):
                    self.sent = []
                async def chat_postMessage(self, **kwargs):
                    self.sent.append(kwargs)
                    return {"ok": True, "message": {"text": kwargs["text"]}}
            slack = Slack()
            await post_briefing(slack, channel="fixture", text="오늘 브리핑", now=NOW,
                               project_path=str(fixture.root), consume=False)
            text = slack.sent[0]["text"]
            self.assertEqual(text.count("오늘의 계정:"), 1)
            self.assertIn("최근 2주 활동 분야", text)
            self.assertEqual(len(slack.sent), 1)
            self.assertFalse((fixture.root / "data/kuromi-delivery.json").exists())
        finally:
            fixture.tearDown()
