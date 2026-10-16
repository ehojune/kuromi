# Culture news validation (lookup only)

2026-10-16, 16:02 KST. Live public feeds plus offline Slack delivery; no real message sent.

| Check | Result |
|---|---|
| Default collection | 18/18 configured sources succeeded; no partial failure |
| Discovery | Generic English/Korean culture queries and HN AI-researcher search. No Palantir/smoking query or pinned article |
| Regression story | Palantir CTO smoking remark: 11 related URLs, including English, Korean and HN records, became one selected topic |
| Morning evidence | Story offered in the only culture slot, alongside ordinary AI candidates |
| Offline delivery | Two ordinary topics + one culture topic; one fake Slack call. Topic suppressed on the next automatic preparation |
| Manual read | Same topic remained available; delivery state unchanged |
| Regressions | 94 tests passed, including different events involving one person, version numbers, stale reports, bilingual anchors, member/source limits and send failure |

Examples: [CBS transcript](https://www.cbsnews.com/news/shyam-sankar-chief-technology-officer-palantir-face-the-nation-transcript-10-11-2026/), [HN discussion](https://news.ycombinator.com/item?id=50073279). The remark is attributable; the claim about researchers' actual smoking habits is not established by grouping or engagement counts.

Boundaries: this validates discovery and candidate selection, not a real Claude-written Slack message or exhaustive social coverage. Lexical clustering and the finite bilingual vocabulary can miss or misgroup paraphrases. See [collection limits](ai-news-sources.md).

One Windows temporary-ledger replacement raised a permission error once; the focused test and full suite passed on rerun. Its cause was not established.
