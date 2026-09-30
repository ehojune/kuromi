"""AI news evidence, freshness, fairness, and failure-boundary regression tests."""
import asyncio
from datetime import datetime, timedelta, timezone
import json
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
import xml.etree.ElementTree as ET

import ai_news_tools as news

NOW = datetime(2026, 10, 1, 9, tzinfo=timezone.utc)


def source(name="official", category="releases", kind="official_release"):
    return {"id": name, "name": name, "url": "https://example.org/feed", "format": "feed",
            "category": category, "type": kind}


def item(name, *, category="releases", age=1, publisher=None, url=None):
    return news._item(source(publisher or name, category), name, url or f"https://example.org/{name}",
                      (NOW - timedelta(days=age)).isoformat())


class ParseTests(unittest.TestCase):
    def test_realistic_rss_google_aggregator_and_publisher(self):
        feed = '''<rss version="2.0"><channel><item><title>Model launch - Publisher</title>
          <link>https://news.google.com/rss/articles/CaseSensitiveID?oc=5</link>
          <pubDate>Wed, 30 Sep 2026 06:00:00 GMT</pubDate>
          <source url="https://publisher.example/">Publisher</source>
          <description>&lt;b&gt;Reported&lt;/b&gt; story</description></item></channel></rss>'''
        got = news.parse_feed(feed, source("google", "articles", "news_article"))[0]
        self.assertEqual(got["publisher"], "Publisher")
        self.assertEqual(got["summary"], "Reported story")
        self.assertTrue(got["is_aggregator"])
        self.assertIsNone(got["original_url"])
        self.assertEqual(got["publisher_url"], "https://publisher.example/")
        self.assertIn("CaseSensitiveID", got["canonical_url"])
        self.assertEqual(got["published_at"], "2026-09-30T06:00:00+00:00")

    def test_atom_alternate_not_self_updated_fallback(self):
        feed = '''<feed xmlns="http://www.w3.org/2005/Atom"><entry>
          <title>v2.1 release</title><id>tag:github.com,2008:x</id>
          <link rel="self" href="https://api.example.org/self"/>
          <link rel="alternate" href="https://github.com/org/repo/releases/tag/v2.1"/>
          <updated>2026-09-30T07:30:00Z</updated><author><name>maintainer</name></author>
          <content type="html">&lt;p&gt;Release notes&lt;/p&gt;</content></entry></feed>'''
        got = news.parse_feed(feed, source())[0]
        self.assertIn("/releases/tag/v2.1", got["url"])
        self.assertEqual(got["date_basis"], "updated")
        self.assertEqual(got["publisher"], "maintainer")
        self.assertFalse(got["is_aggregator"])

    def test_arxiv_preserves_published_and_updated_separately(self):
        feed = '''<feed xmlns="http://www.w3.org/2005/Atom"><entry>
          <title>A Multi-Agent Survey</title><id>http://arxiv.org/abs/2609.12345v2</id>
          <published>2026-08-01T00:00:00Z</published><updated>2026-09-30T00:00:00Z</updated>
          <summary>Preprint summary</summary></entry></feed>'''
        got = news.parse_feed(feed, source("arxiv", "research", "research_preprint"))[0]
        self.assertEqual(got["date_basis"], "published")
        self.assertEqual(got["type"], "research_preprint")
        self.assertEqual(news.select_items([got], 7, 10, NOW), [])

    def test_unknown_and_malformed_xml_are_errors(self):
        with self.assertRaises(ET.ParseError):
            news.parse_feed("<rss><channel>", source())
        with self.assertRaises(ValueError):
            news.parse_feed("<html/>", source())

    def test_xml_entities_rejected(self):
        with self.assertRaises(ValueError):
            news.parse_feed('<!DOCTYPE x [<!ENTITY x "danger">]><rss/>', source())

    def test_missing_date_is_not_invented(self):
        got = news.parse_feed('<rss><channel><item><title>Unknown</title><link>https://example.org/x</link>'
                              '</item></channel></rss>', source())[0]
        self.assertIsNone(got["published_at"])
        self.assertEqual(news.select_items([got], 7, 10, NOW), [])

    def test_bad_date_and_non_http_url(self):
        self.assertIsNone(news.parse_date("September-ish"))
        self.assertIsNone(news.parse_date("Feb 31, 2026"))
        self.assertIsNone(news._item(source(), "bad", "javascript:alert(1)", "2026-09-30"))
        self.assertEqual(news.canonical_url("https://name:secret@example.org/x"), "")

    def test_canonical_url_tracking_and_semantic_query(self):
        self.assertEqual(news.canonical_url("https://EXAMPLE.org:443/x/?b=2&utm_source=q&id=1#section"),
                         "https://example.org/x?b=2&id=1")
        self.assertNotEqual(news.canonical_url("https://news.hada.io/topic?id=1"),
                            news.canonical_url("https://news.hada.io/topic?id=2"))

    def test_anthropic_dated_anchor_titles_and_datetime(self):
        html = '''<a href="/news/release"><time datetime="2026-09-30">Sep 30, 2026</time>
          <span class="PublicationList-module__title body-3">A <b>new</b> release</span></a>
          <a href="/claude-sonnet"><h2 class="Featured__title">Claude Sonnet</h2>
          <time>Sep 28, 2026</time><p>Official announcement</p></a>
          <a href="/news/undated"><h3>Missing date</h3></a>'''
        got = news.parse_anthropic_html(html, {**source(), "url": "https://www.anthropic.com/news"})
        self.assertEqual(len(got), 2)
        self.assertEqual(got[0]["title"], "A new release")
        self.assertEqual(got[0]["url"], "https://www.anthropic.com/news/release")
        self.assertEqual(got[1]["summary"], "Official announcement")

    def test_anthropic_changed_layout_exposes_failure(self):
        with self.assertRaises(ValueError):
            news.parse_anthropic_html('<a href="/news/x">No date/title tags</a>', source())

    def test_keyword_boundaries_avoid_paid_matching_ai(self):
        self.assertFalse(news._matches({"title": "Paid software", "summary": "Daily update"}, ["ai"]))
        self.assertTrue(news._matches({"title": "AI agents", "summary": ""}, ["ai"]))
        self.assertTrue(news._matches({"title": "독파모 소식", "summary": ""}, ["독파모"]))


class RankingTests(unittest.TestCase):
    def test_strict_freshness_excludes_old_undated_and_future(self):
        candidates = [item("today", age=0), item("edge", age=7), item("old", age=8),
                      item("future", age=-1), news._item(source(), "undated", "https://example.org/u", "")]
        self.assertEqual({x["title"] for x in news.select_items(candidates, 7, 10, NOW)}, {"today", "edge"})

    def test_dedupe_canonical_url_prefers_official(self):
        official = item("Official", url="https://example.org/story?utm_medium=rss")
        syndicated = item("Syndicated", url="https://example.org/story#ref")
        syndicated["type"] = "news_article"
        got = news.select_items([syndicated, official], 7, 10, NOW)
        self.assertEqual([x["title"] for x in got], ["Official"])

    def test_syndicated_news_headline_dedupe_does_not_merge_release_tags(self):
        first = news._item(source("a", "policy_kr", "policy_news"), "독파모 소식 - Publisher A",
                           "https://news.google.com/articles/a", "2026-09-30", publisher="Publisher A")
        second = news._item(source("b", "policy_kr", "policy_news"), "독파모 소식 - Publisher B",
                            "https://news.google.com/articles/b", "2026-09-30", publisher="Publisher B")
        releases = [item("v1.0", url=f"https://example.org/{i}", publisher=str(i)) for i in range(2)]
        self.assertEqual(len(news.select_items([first, second] + releases, 7, 10, NOW)), 3)

    def test_release_flood_does_not_starve_categories_or_sources(self):
        candidates = [item(f"release{i}", publisher="claude-code", age=i / 50) for i in range(30)]
        candidates.extend([item("OpenAI", publisher="openai"), item("Kimi", category="kimi"),
                           item("Opinion", category="user_reviews"), item("Survey", category="research"),
                           item("US", category="policy_us"), item("KR", category="policy_kr")])
        got = news.select_items(candidates, 7, 8, NOW)
        self.assertEqual(len(got), 8)
        self.assertEqual(len({x["category"] for x in got}), 6)
        self.assertIn("OpenAI", [x["title"] for x in got])

    def test_budget_validation(self):
        self.assertEqual(news._integer("bad", 7, 1, 90), 7)
        self.assertEqual(news._integer(-10, 7, 1, 90), 1)
        self.assertEqual(news._integer(1000, 7, 1, 90), 90)

    def test_query_url_encoded_language_and_window(self):
        config = {"format": "google_news", "query": "독파모 & AI", "language": "ko"}
        result = urlsplit(news._request_url(config, 14))
        self.assertEqual(result.hostname, "news.google.com")
        query = parse_qs(result.query)
        self.assertEqual(query["q"], ["독파모 & AI when:14d"])
        self.assertEqual(query["ceid"], ["KR:ko"])

    def test_registry_coverage_and_fixed_budget(self):
        sources = news._load_sources()
        self.assertLessEqual(len(sources), news._MAX_SOURCES)
        self.assertEqual({s["category"] for s in sources}, set(news._CATEGORIES))
        self.assertIn("claude-code", {s["id"] for s in sources})


class AsyncCollectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_response_byte_budget(self):
        class Content:
            async def iter_chunked(self, size):
                yield b"x" * 10
                yield b"x" * 10
        class Response:
            content = Content()
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass
            def raise_for_status(self):
                pass
        class Session:
            def get(self, *args, **kwargs):
                return Response()
        with patch.object(news, "_MAX_BYTES", 15):
            with self.assertRaises(ValueError):
                await news._fetch_source(Session(), source(), 7)

    async def test_google_relevance_requires_title_terms(self):
        class Content:
            async def iter_chunked(self, size):
                yield (f'<rss><channel><item><title>Meta announcement</title><link>https://example.org/meta</link>'
                       f'<pubDate>{datetime.now(timezone.utc).isoformat()}</pubDate>'
                       f'<description>Compared to Kimi</description></item></channel></rss>').encode()
        class Response:
            content = Content()
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass
            def raise_for_status(self):
                pass
        class Session:
            def get(self, *args, **kwargs):
                return Response()
        got = await news._fetch_source(Session(), {**source(), "title_groups": [["kimi", "moonshot"]]}, 7)
        self.assertEqual(got, [])

    async def test_partial_failure_retains_results_and_hides_secrets(self):
        async def fetch(session, config, days):
            if config["id"] == "broken":
                raise RuntimeError("proxy password=hunter2 token=secret")
            return [item("Working", publisher=config["id"])]
        with patch.object(news, "_fetch_source", side_effect=fetch):
            got = await news.collect_ai_news(sources=[source("working"), source("broken")], now=NOW)
        self.assertTrue(got["partial_failure"])
        self.assertEqual(len(got["items"]), 1)
        self.assertNotIn("hunter2", json.dumps(got))
        self.assertEqual(got["sources"][0]["reason"], "source_error")

    async def test_total_timeout_retains_completed_sources(self):
        async def fetch(session, config, days):
            if config["id"] == "slow":
                await asyncio.sleep(2)
            return [item("Working", publisher=config["id"])]
        with patch.object(news, "_fetch_source", side_effect=fetch), patch.object(news, "_TOTAL_TIMEOUT", 0.03):
            got = await news.collect_ai_news(sources=[source("working"), source("slow")], now=NOW)
        self.assertEqual(len(got["items"]), 1)
        self.assertTrue(got["partial_failure"])
        self.assertEqual(next(s for s in got["sources"] if s["id"] == "slow")["reason"], "total_timeout")

    async def test_concurrency_and_source_limit(self):
        active = peak = calls = 0
        async def fetch(session, config, days):
            nonlocal active, peak, calls
            calls += 1
            active += 1
            peak = max(active, peak)
            await asyncio.sleep(0.001)
            active -= 1
            return []
        with patch.object(news, "_fetch_source", side_effect=fetch):
            got = await news.collect_ai_news(sources=[source(str(i)) for i in range(30)], now=NOW)
        self.assertEqual(calls, news._MAX_SOURCES)
        self.assertLessEqual(peak, 4)
        self.assertFalse(got["partial_failure"])

    async def test_custom_query_only_public_search_sources(self):
        configs = []
        async def fetch(session, config, days):
            configs.append(config)
            return []
        with patch.object(news, "_fetch_source", side_effect=fetch):
            await news.collect_ai_news(query="GPT Astra reviews", now=NOW)
        self.assertEqual(len(configs), 2)
        self.assertTrue(all(config["format"] == "google_news" for config in configs))
        with self.assertRaises(ValueError):
            await news.collect_ai_news(query="   ", now=NOW)


if __name__ == "__main__":
    unittest.main()
