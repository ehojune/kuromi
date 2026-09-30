# AI news sources — lookup only

Verified live on 2026-10-01. This file records collection limits and source provenance.

| Lane | Sources | Evidence type |
|---|---|---|
| Official | [Anthropic](https://www.anthropic.com/news), [Claude Code](https://github.com/anthropics/claude-code/releases.atom), [OpenAI](https://openai.com/news/rss.xml), [Cursor](https://cursor.com/changelog/rss.xml), [Kimi CLI](https://github.com/MoonshotAI/kimi-cli/releases.atom) | Dated announcements/releases |
| Industry | [TechCrunch AI](https://techcrunch.com/category/artificial-intelligence/feed/), [The Verge AI](https://www.theverge.com/rss/ai-artificial-intelligence/index.xml), Google News industry search | News reporting |
| Community | [GeekNews](https://news.hada.io/rss/news), [Simon Willison](https://simonwillison.net/atom/everything/) | Community links / expert opinion |
| Targeted | Google News Kimi, GPT Astra reviews, Trump AI/SI, 독파모 | Search metadata, not validated claims |
| Research | [arXiv API](https://export.arxiv.org/api/query) | LLM multiagent survey/review preprints |

- Registry: `ai-news-sources.json`. No paid API or Slack/Claude credentials for collection.
- `recent_ai_news`: days 1–90, results 1–30. `search_ai_news`: Korean/English Google News queries.
- Official releases get the first category slot. Categories and sources take turns so frequent Claude Code releases cannot fill the whole digest.
- Dates must exist, fall inside the requested window, and precede collection time. arXiv uses original publication date; a revision does not turn an old paper into a new one.
- Google News and GeekNews discussion URLs are marked as aggregator links. `publisher_url` is the publisher homepage; it is never presented as the original article. Read the original before making detailed claims.
- Canonical URLs remove tracking parameters. Exact syndicated news headlines on the same date are also collapsed. Release tags remain separate across repositories.
- Each request: 12 seconds / 2 MB. Collection: 45 seconds, 4 concurrent requests, at most 16 sources / 25 items per source. Failed sources return short error codes.
- Queries and previews are read-only. The daily briefing owns delivery records after a successful Slack post.
- Live 7-day smoke: 15/15 sources parsed; no fresh Cursor/Kimi CLI release or arXiv survey in that window. An empty source does not imply network failure.

Smoke without running the assistant:

```powershell
python ai_news_tools.py --json --days 7 --max-results 12
python -m unittest discover -s tests -p 'test_ai_news*.py'
```
