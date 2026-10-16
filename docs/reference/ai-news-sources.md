# AI news sources — lookup only

Verified live on 2026-10-16. This file records collection limits and source provenance.

| Lane | Sources | Evidence type |
|---|---|---|
| Official | [Anthropic](https://www.anthropic.com/news), [Claude Code](https://github.com/anthropics/claude-code/releases.atom), [OpenAI](https://openai.com/news/rss.xml), [Cursor](https://cursor.com/changelog/rss.xml), [Kimi CLI](https://github.com/MoonshotAI/kimi-cli/releases.atom) | Dated announcements/releases |
| Industry | [TechCrunch AI](https://techcrunch.com/category/artificial-intelligence/feed/), [The Verge AI](https://www.theverge.com/rss/ai-artificial-intelligence/index.xml), Google News industry search | News reporting |
| Community | [GeekNews](https://news.hada.io/rss/news), [Simon Willison](https://simonwillison.net/atom/everything/) | Community links / expert opinion |
| People/culture/debate | English/Korean Google News queries, [HN search API](https://hn.algolia.com/api) | Reporting and public story metadata; HN points/comment counts, no comment bodies |
| Targeted | Google News Kimi, GPT Astra reviews, Trump AI/SI, 독파모 | Search metadata, not validated claims |
| Research | [arXiv API](https://export.arxiv.org/api/query) | LLM multiagent survey/review preprints |

- Registry: `ai-news-sources.json`. No paid API or Slack/Claude credentials for collection.
- `recent_ai_news`: days 1–90, results 1–30. `search_ai_news`: Korean/English Google News queries.
- Official releases get the first category slot. Categories and sources take turns so frequent Claude Code releases cannot fill the whole digest.
- Dates must exist, fall inside the requested window, and precede collection time. arXiv uses original publication date; a revision does not turn an old paper into a new one.
- Google News and GeekNews discussion URLs are marked as aggregator links. `publisher_url` is the publisher homepage; it is never presented as the original article. Read the original before making detailed claims.
- Canonical URLs remove tracking parameters. News groups retain related links and publishers. Similar specific headline words within four days, or a known bilingual entity plus two shared topic anchors, can join a topic. Releases and research are not fuzzily grouped.
- Grouping is conservative, not general translation or fact checking. Unknown aliases/paraphrases may remain separate; similar headlines can still be misgrouped. At most 50 members are exposed per topic; truncation is labelled.
- Each request: 12 seconds / 2 MB. Collection: 45 seconds, 4 concurrent requests, at most 20 sources / 25 topics per source. HN inspects at most 100 search hits; feed/search windows are not exhaustive archives. Failed or excess sources return error/limit codes.
- Morning evidence offers at most one culture topic among ten candidates. The existing AI section stays at 2–3 items, with culture optional and at most one. Known linked news lines are capped at three, and culture at one, after generation and before sending. Task/paper links are preserved.
- Culture spread/engagement counts measure attention, never truth or representative developer opinion. Quotation authenticity and the truth of the quoted claim remain distinct.
- Confirmed delivery records the chosen topic's URL aliases and headline receipts; later close paraphrases are suppressed. Manual queries/briefings never consume these records. Existing URL-only ledgers remain readable.
- Queries and previews are read-only. The daily briefing owns delivery records after a successful Slack post.
- Live 7-day smoke: 18/18 sources parsed. The Palantir smoking remark was found with generic queries, grouped across English/Korean reports, and offered in the single culture slot. [Validation](culture-news.md). An empty source does not imply network failure.

Smoke without running the assistant:

```powershell
python ai_news_tools.py --json --days 7 --max-results 12
python -m unittest discover -s tests -p 'test_ai_news*.py'
```
