"""논문 스카우트: PubMed(E-utilities)로 관심사 기반 최신 논문을 가져오고,
관심사 파일(research-interests.md)을 관리(추가/제외)한다.

'외부 검색 허용' 결정에 따라 논문 '발굴'에만 외부(PubMed)를 쓴다. API 키 불필요.
TLS 프록시 대응은 net.py(truststore) — 이 모듈을 쓰는 프로세스가 먼저 import 할 것.
"""
import asyncio
import json
import re
from pathlib import Path

import aiohttp

from claude_agent_sdk import tool
from config import load_config

_EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
_TIMEOUT = aiohttp.ClientTimeout(total=20)
_QUERIES_H = "## PubMed queries"
_EXCLUDED_H = "## Excluded topics"


# ─────────────────────────── PubMed ───────────────────────────
def _params(base: dict) -> dict:
    cfg = load_config()
    base["tool"] = "kuromi"
    if cfg.ncbi_email:
        base["email"] = cfg.ncbi_email
    return base


async def _esearch(session, term, days, retmax):
    params = _params({
        "db": "pubmed", "term": term, "retmode": "json", "sort": "date",
        "retmax": str(retmax), "datetype": "pdat", "reldate": str(days),
    })
    async with session.get(f"{_EUTILS}/esearch.fcgi", params=params, timeout=_TIMEOUT) as r:
        data = await r.json()
    return data.get("esearchresult", {}).get("idlist", [])


async def _esummary(session, ids):
    if not ids:
        return []
    params = _params({"db": "pubmed", "id": ",".join(ids), "retmode": "json"})
    async with session.get(f"{_EUTILS}/esummary.fcgi", params=params, timeout=_TIMEOUT) as r:
        data = await r.json()
    result = data.get("result", {})
    out = []
    for pid in result.get("uids", []):
        it = result.get(pid, {})
        doi = next((a.get("value", "") for a in it.get("articleids", [])
                    if a.get("idtype") == "doi"), "")
        out.append({
            "pmid": pid,
            "title": (it.get("title") or "").strip(),
            "journal": it.get("fulljournalname") or it.get("source", ""),
            "date": it.get("pubdate", ""),
            "doi": doi,
        })
    return out


def _fmt(papers):
    lines = []
    for p in papers:
        link = f"https://doi.org/{p['doi']}" if p["doi"] else f"https://pubmed.ncbi.nlm.nih.gov/{p['pmid']}/"
        lines.append(f"- {p['title']} ({p['journal']}, {p['date']}) {link}")
    return "\n".join(lines)


# ────────────────────── 관심사 파일 관리 ──────────────────────
def _path():
    return load_config().interests_path


def _lines():
    try:
        with open(_path(), encoding="utf-8") as f:
            return f.read().splitlines()
    except OSError:
        return []


def _save(lines):
    with open(_path(), "w", encoding="utf-8") as f:
        f.write("\n".join(lines).rstrip() + "\n")


def _bounds(lines, header):
    """섹션 헤더의 (시작 index, 끝 index 배타) 반환. 없으면 (None, None)."""
    hl = header.strip().lower()
    start = next((i for i, ln in enumerate(lines) if ln.strip().lower() == hl), None)
    if start is None:
        return None, None
    end = next((j for j in range(start + 1, len(lines)) if lines[j].startswith("## ")), len(lines))
    return start, end


def _bullets(header):
    lines = _lines()
    s, e = _bounds(lines, header)
    if s is None:
        return []
    out = []
    for ln in lines[s + 1:e]:
        if (m := re.match(r"\s*[-*]\s+(.+)", ln)):
            out.append(m.group(1).strip())
    return out


def _read_interest_queries():
    return _bullets(_QUERIES_H)


def _read_excluded():
    return _bullets(_EXCLUDED_H)


# ──────────────── llm-wiki 유래 관심사 (interests.json, 가중치) ────────────────
def _wiki_interests_path() -> Path:
    return Path(load_config().wiki_path) / "interests.json"


def _read_wiki_interests():
    """llm-wiki/scan_interests.py 가 만든 interests.json 을 읽어
    [{'tag','score'}, ...] 를 점수 내림차순으로 돌려준다. 없으면 []."""
    try:
        data = json.loads(_wiki_interests_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    topics = data.get("topics", [])
    topics.sort(key=lambda t: t.get("score", 0), reverse=True)
    return topics


def _wiki_count(score: float, base: int) -> int:
    """관심 점수가 높을수록 그 주제에서 더 많은 논문을 가져온다."""
    if score >= 3.0:
        return base + 2
    if score >= 2.0:
        return base + 1
    return base


def _build_query_plan(per: int, wiki_top: int):
    """수동 '## PubMed queries' + interests.json(가중치) 를 합쳐 검색 계획을 만든다.
    각 항목: {'label','term','count'}. 제외 주제/중복은 걸러낸다."""
    excluded = [x.lower() for x in _read_excluded()]

    def blocked(text: str) -> bool:
        t = text.lower()
        return any(x in t for x in excluded)

    plan, seen_terms = [], set()

    # 1) 사용자가 손으로 적은 쿼리 — 항상 포함, 기본 개수.
    for q in _read_interest_queries():
        if blocked(q) or q.lower() in seen_terms:
            continue
        plan.append({"label": q, "term": q, "count": per})
        seen_terms.add(q.lower())

    # 2) 위키 유래 관심사 — 점수 순으로 상위 wiki_top개, 점수로 개수 가중.
    for it in _read_wiki_interests()[:wiki_top]:
        tag = it.get("tag", "")
        score = float(it.get("score", 0))
        term = tag.replace("-", " ").strip()
        if not term or blocked(term) or blocked(tag) or term.lower() in seen_terms:
            continue
        plan.append({"label": f"{term} ★{score:.1f}", "term": term,
                     "count": _wiki_count(score, per)})
        seen_terms.add(term.lower())

    return plan, excluded


def _add_bullet(header, item):
    lines = _lines()
    s, e = _bounds(lines, header)
    if s is None:  # 섹션이 없으면 새로 만든다
        if lines and lines[-1].strip():
            lines.append("")
        lines += [header, f"- {item}"]
    else:
        lines.insert(e, f"- {item}")
    _save(lines)


def _remove_bullet(header, needle):
    lines = _lines()
    s, e = _bounds(lines, header)
    if s is None:
        return False
    removed, kept = False, []
    for idx, ln in enumerate(lines):
        if s < idx < e and (m := re.match(r"\s*[-*]\s+(.+)", ln)):
            if needle.lower() in m.group(1).strip().lower():
                removed = True
                continue
        kept.append(ln)
    if removed:
        _save(kept)
    return removed


# ─────────────────────────── 도구 ───────────────────────────
@tool(
    "search_pubmed",
    "PubMed에서 최근 논문을 검색한다. term(검색어), days(최근 며칠, 기본 30), max_results(기본 8).",
    {"term": str, "days": int, "max_results": int},
)
async def search_pubmed(args):
    term = (args.get("term") or "").strip()
    if not term:
        return {"content": [{"type": "text", "text": "검색어가 비었어요."}]}
    days = int(args.get("days") or 30)
    n = int(args.get("max_results") or 8)
    try:
        async with aiohttp.ClientSession() as s:
            papers = await _esummary(s, await _esearch(s, term, days, n))
    except Exception as e:
        return {"content": [{"type": "text", "text": f"[PubMed 오류] {e}"}]}
    if not papers:
        return {"content": [{"type": "text", "text": f"'{term}' 최근 {days}일 신규 논문 없음."}]}
    return {"content": [{"type": "text", "text": f"[{term}] 최근 {days}일:\n" + _fmt(papers)}]}


@tool(
    "recent_papers_for_interests",
    "관심사별로 PubMed 최근 논문을 모아온다. 수동 '## PubMed queries' 와 llm-wiki 유래 "
    "관심사(interests.json, 점수 가중)를 합쳐 쓴다(제외 주제는 걸러냄). 점수 높은 주제일수록 "
    "더 많이 가져옴. 아침 브리핑/논문 추천에 사용. days(기본 14), per_topic(기본 4), wiki_top(기본 10).",
    {"days": int, "per_topic": int, "wiki_top": int},
)
async def recent_papers_for_interests(args):
    days = int(args.get("days") or 14)
    per = int(args.get("per_topic") or 4)
    wiki_top = int(args.get("wiki_top") or 10)

    plan, excluded = _build_query_plan(per, wiki_top)
    if not plan:
        return {"content": [{"type": "text",
                             "text": "관심사가 비었어요. '## PubMed queries' 를 적거나 llm-wiki 를 쌓아주세요."}]}

    def _blocked(text):
        t = text.lower()
        return any(x in t for x in excluded)

    blocks, seen = [], set()
    try:
        async with aiohttp.ClientSession() as s:
            for item in plan:
                papers = await _esummary(s, await _esearch(s, item["term"], days, item["count"]))
                fresh = [p for p in papers
                         if p["pmid"] not in seen and not _blocked(p["title"])]
                for p in fresh:
                    seen.add(p["pmid"])
                if fresh:
                    blocks.append(f"[{item['label']}]\n" + _fmt(fresh))
                await asyncio.sleep(0.34)  # NCBI 예의 (초당 ≤3건)
    except Exception as e:
        return {"content": [{"type": "text", "text": f"[PubMed 오류] {e}"}]}

    if not blocks:
        return {"content": [{"type": "text", "text": f"최근 {days}일 관심사 관련 신규 논문이 없어요."}]}
    note = "(★ = llm-wiki 관심 점수)"
    return {"content": [{"type": "text",
                         "text": f"최근 {days}일 관심사별 신규 논문 {note}:\n\n" + "\n\n".join(blocks)}]}


@tool(
    "add_interest_topic",
    "관심사 파일에 새 PubMed 검색 주제를 추가한다. 사용자가 새 분야/프로젝트에 관심 생겼다고 하면 사용.",
    {"topic": str},
)
async def add_interest_topic(args):
    topic = (args.get("topic") or "").strip()
    if not topic:
        return {"content": [{"type": "text", "text": "주제가 비었어요."}]}
    if topic.lower() in [q.lower() for q in _read_interest_queries()]:
        return {"content": [{"type": "text", "text": f"이미 있는 주제예요: {topic}"}]}
    _add_bullet(_QUERIES_H, topic)
    return {"content": [{"type": "text", "text": f"관심사에 추가함: {topic}"}]}


@tool(
    "remove_interest_topic",
    "관심사에서 주제를 뺀다(그리고 제외 목록에 넣어 더는 추천하지 않음). "
    "사용자가 '○○는 추천하지 마' 라고 하면 사용.",
    {"topic": str},
)
async def remove_interest_topic(args):
    topic = (args.get("topic") or "").strip()
    if not topic:
        return {"content": [{"type": "text", "text": "주제가 비었어요."}]}
    removed = _remove_bullet(_QUERIES_H, topic)
    if topic.lower() not in [x.lower() for x in _read_excluded()]:
        _add_bullet(_EXCLUDED_H, topic)
    msg = f"'{topic}' 관심사에서 제거하고 제외 목록에 넣었어요." if removed \
        else f"'{topic}'는 관심사 목록엔 없었지만 제외 목록에 넣었어요."
    return {"content": [{"type": "text", "text": msg}]}
