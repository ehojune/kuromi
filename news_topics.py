"""Conservative headline clustering; metadata is evidence, never instructions."""
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import hashlib
import json
import re
import unicodedata

_NEWS = {"news_article", "policy_news", "community_news", "expert_opinion",
         "review_search_result", "search_result"}
_STOP = set("a an the and or of to in on for as at by with from is are was were be been "
            "it its this that their they them some many more so how why what who when "
            "will would could should have has had do does not no into up out than "
            "ai agi llm artificial intelligence ceo cto exec chief officer say says said "
            "claim claims report reports new news researchers researcher believe believes "
            "started start taking take show prove because think thinks even".split())
_MAX_MEMBERS = 50
_TOPIC_PREFIX = "ai-topic:v1:"
# Bounded bilingual anchors improve Korean/English grouping without translating quotations.
# An entity plus TWO shared topic anchors is required; these never trigger collection queries.
_ENTITIES = {"palantir": r"\bpalantir\b|팔란티어", "microsoft": r"\bmicrosoft\b|마이크로소프트",
             "openai": r"\bopenai\b|오픈에이아이|오픈AI", "anthropic": r"\banthropic\b|앤스로픽|안트로픽",
             "nvidia": r"\bnvidia\b|엔비디아", "google": r"\bgoogle\b|구글",
             "meta": r"\bmeta\b|메타", "apple": r"\bapple\b|애플",
             "amazon": r"\bamazon\b|아마존", "broadcom": r"\bbroadcom\b|브로드컴"}
_TOPICS = {"tobacco": r"\b(?:smok\w*|cigarette\w*|tobacco)\b|담배|흡연",
           "cancer": r"\bcancer\b|(?<![가-힣])암(?:을|은|이|에|도|과)?(?![가-힣])",
           "layoff": r"\b(?:layoff\w*|job cuts|workforce reduction)\b|해고|감원",
           "copyright": r"\bcopyright\b|저작권", "privacy": r"\bprivacy\b|개인정보",
           "safety": r"\bsafety\b|안전", "lawsuit": r"\blawsuit\w*\b|소송",
           "workforce": r"\bworkforce\b|인력"}


@lru_cache(maxsize=2048)
def _anchors(title):
    return ({name for name, pattern in _ENTITIES.items() if re.search(pattern, title, re.I)},
            {name for name, pattern in _TOPICS.items() if re.search(pattern, title, re.I)})


def _date(item):
    try:
        value = datetime.fromisoformat(item.get("published_at", "").replace("Z", "+00:00"))
        return value.astimezone(timezone.utc) if value.tzinfo else None
    except (ValueError, TypeError, AttributeError):
        return None


def _tokens(item):
    title = unicodedata.normalize("NFKC", item.get("title", "")).casefold()
    publisher = item.get("publisher", "").casefold()
    if publisher and title.endswith(" - " + publisher):
        title = title[:-(len(publisher) + 3)]
    words = re.findall(r"[a-z][a-z0-9]*|[가-힣]{2,}|\d+(?:\.\d+)*", title)
    result = set()
    for word in words:
        if word in _STOP:
            continue
        # Small inflection normalization, not a claim of semantic equivalence.
        if word.isascii() and word.isalpha():
            if len(word) > 5 and word.endswith("ing"):
                word = word[:-3]
            elif len(word) > 5 and word.endswith("ed"):
                word = word[:-2]
            elif len(word) > 4 and word.endswith("s"):
                word = word[:-1]
            if len(word) >= 5 and word.endswith("e"):
                word = word[:-1]
        if len(word) >= 2 or word[0].isdigit():
            result.add(word)
    return result


def same_topic(left, right):
    """Require close dates and several shared specific words; keep releases separate."""
    if left.get("type") not in _NEWS or right.get("type") not in _NEWS:
        return False
    a, b = _date(left), _date(right)
    if not a or not b or abs(a - b) > timedelta(days=4):
        return False
    x, y = _tokens(left), _tokens(right)
    if x and x == y:
        return True
    # Do not fuse different version numbers or numerical claims.
    nx = {w for w in x if any(c.isdigit() for c in w)}
    ny = {w for w in y if any(c.isdigit() for c in w)}
    if nx and ny and nx != ny:
        return False
    if re.search(r"[가-힣]", left.get("title", "") + right.get("title", "")):
        le, lt = _anchors(left.get("title", ""))
        re_, rt = _anchors(right.get("title", ""))
        if le & re_ and len(lt & rt) >= 2:
            return True
    shared = x & y
    if len(shared) < 3:
        return False
    return len(shared) / len(x | y) >= 0.45 or len(shared) / min(len(x), len(y)) >= 0.8


def members(item):
    return [item] + item.get("related_items", [])[:_MAX_MEMBERS - 1]


def group_topics(items):
    """Collapse URL/headline variants before per-source/category caps."""
    groups = []
    for item in items:
        for row in members(item):
            row = {k: v for k, v in row.items() if k not in
                   {"related_items", "report_count", "topic_id", "publishers"}}
            url = row.get("canonical_url") or row.get("url")
            matching = [g for g in groups if any(
                url == (old.get("canonical_url") or old.get("url")) or same_topic(row, old)
                for old in g)]
            if not matching:
                groups.append([row])
                continue
            target = matching[0]
            for other in matching[1:]:
                target.extend(other)
                groups.remove(other)
            if not any(url == (old.get("canonical_url") or old.get("url")) for old in target):
                target.append(row)
            elif row.get("category") == "culture":
                # Preserve the culture label even when another feed supplied this URL first.
                for old in target:
                    if url == (old.get("canonical_url") or old.get("url")) and old.get("type") in _NEWS:
                        old["category"] = "culture"
            for old in target:
                if url == (old.get("canonical_url") or old.get("url")):
                    for name in ("community_comments", "community_points"):
                        if name in row:
                            old[name] = max(old.get(name, 0), row[name])
                    if row.get("discussion_url"):
                        old["discussion_url"] = row["discussion_url"]
    result = []
    for group in groups:
        group.sort(key=lambda x: (x.get("is_aggregator", False),
                                 not x.get("type", "").startswith("official"),
                                 x.get("published_at") or "", x.get("url", "")))
        representative = dict(group[0])
        if representative.get("type") in _NEWS and any(x.get("category") == "culture" for x in group):
            representative["category"] = "culture"
        if len(group) > 1:
            representative["related_items"] = group[1:_MAX_MEMBERS]
            representative["report_count"] = len(group)
            representative["publishers"] = sorted({x.get("publisher", "") for x in group if x.get("publisher")})
            representative["topic_id"] = "news:" + hashlib.sha256(representative["url"].encode()).hexdigest()[:24]
            if len(group) > _MAX_MEMBERS or any(x.get("topic_members_truncated") for x in group):
                representative["topic_members_truncated"] = True
        result.append(representative)
    return result


def culture_rank(item):
    """Rank observed discussion/spread, never interpret it as verification of a claim."""
    rows = members(item)
    publishers = {x.get("publisher") for x in rows if x.get("publisher")}
    comments = max((min(x.get("community_comments", 0), 100) for x in rows), default=0)
    return (min(len(publishers), 5), comments, item.get("published_at") or "", item.get("url", ""))


def delivery_aliases(item):
    return sorted({"ai:" + str(x.get("canonical_url") or x.get("url")) for x in members(item)
                   if x.get("canonical_url") or x.get("url")})


def topic_receipts(item):
    """Stored only after confirmed delivery; ordinary collection never writes state."""
    return [_TOPIC_PREFIX + json.dumps({"title": x["title"][:250], "published_at": x["published_at"],
                                       "type": x["type"], "publisher": x.get("publisher", "")},
                                      ensure_ascii=False, sort_keys=True)
            for x in members(item) if x.get("type") in _NEWS and _date(x)]


def was_delivered(item, ledger):
    if any(key in ledger for key in delivery_aliases(item)):
        return True
    for key in ledger:
        if not key.startswith(_TOPIC_PREFIX) or len(key) > 2000:
            continue
        try:
            prior = json.loads(key[len(_TOPIC_PREFIX):])
            if isinstance(prior, dict) and any(same_topic(x, prior) for x in members(item)):
                return True
        except (ValueError, TypeError):
            continue
    return False
