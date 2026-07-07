"""Notion 도구: [kobic] 우선순위 트래커 + 일정 미러 DB 읽기/쓰기.

라이브러리 버전 이슈를 피하려고 Notion REST API(안정 버전 2022-06-28)를 aiohttp 로 직접 호출한다.
TLS 프록시 대응은 net.py(truststore)가 담당 — 이 모듈을 쓰는 프로세스가 먼저 import 할 것.
"""
import datetime as dt

import aiohttp

from claude_agent_sdk import tool
from config import load_config

_API = "https://api.notion.com/v1"
_VER = "2022-06-28"
_TIMEOUT = aiohttp.ClientTimeout(total=25)
_DONE = {"Done", "Tentatively done", "over"}  # '완료' 그룹 상태


def _headers() -> dict:
    cfg = load_config()
    if not cfg.notion_token:
        raise RuntimeError("NOTION_TOKEN 미설정")
    return {
        "Authorization": f"Bearer {cfg.notion_token}",
        "Notion-Version": _VER,
        "Content-Type": "application/json",
    }


async def _query_db(db_id: str, body: dict | None = None) -> list:
    async with aiohttp.ClientSession() as s:
        async with s.post(f"{_API}/databases/{db_id}/query", headers=_headers(),
                          json=body or {"page_size": 100}, timeout=_TIMEOUT) as r:
            data = await r.json()
    if data.get("object") == "error":
        raise RuntimeError(f"{data.get('status')} {data.get('code')}: {data.get('message')}")
    return data.get("results", [])


async def _create_page(db_id: str, properties: dict) -> dict:
    async with aiohttp.ClientSession() as s:
        async with s.post(f"{_API}/pages", headers=_headers(),
                          json={"parent": {"database_id": db_id}, "properties": properties},
                          timeout=_TIMEOUT) as r:
            data = await r.json()
    if data.get("object") == "error":
        raise RuntimeError(f"{data.get('status')} {data.get('code')}: {data.get('message')}")
    return data


# --- property 추출 헬퍼 ---
def _title(props, name):
    return "".join(t.get("plain_text", "") for t in props.get(name, {}).get("title", [])).strip()

def _text(props, name):
    return "".join(t.get("plain_text", "") for t in props.get(name, {}).get("rich_text", [])).strip()

def _status(props, name="Status"):
    s = props.get(name, {}).get("status")
    return s.get("name") if s else None

def _date(props, name):
    d = props.get(name, {}).get("date")
    return d.get("start") if d else None

def _multi(props, name):
    return [o.get("name") for o in props.get(name, {}).get("multi_select", [])]


@tool(
    "notion_today_tasks",
    "우선순위 트래커에서 아직 안 끝난 할 일을 마감일 순으로 가져온다. "
    "오늘 일정/오늘 할 일/이번 주 할 일을 물으면 사용.",
    {},
)
async def notion_today_tasks(args):
    try:
        cfg = load_config()
        results = await _query_db(cfg.tracker_db_id)
    except Exception as e:
        return {"content": [{"type": "text", "text": f"[Notion 오류] {e}"}]}

    today = dt.date.today().isoformat()
    rows = []
    for page in results:
        p = page.get("properties", {})
        if _status(p) in _DONE:
            continue
        rows.append({
            "task": _title(p, "task"),
            "status": _status(p),
            "due": _date(p, "Due"),
            "project": _multi(p, "project"),
            "notes": _text(p, "Notes"),
        })
    rows.sort(key=lambda r: (r["due"] is None, r["due"] or "9999"))

    if not rows:
        return {"content": [{"type": "text", "text": "진행 중인 할 일이 없어요 (트래커 비어있음)."}]}

    lines = [f"오늘 날짜: {today}", f"미완료 할 일 {len(rows)}개 (마감 순):"]
    for r in rows:
        due = r["due"] or "-"
        mark = " ⚠️오늘/지남" if (r["due"] and r["due"] <= today) else ""
        proj = f" [{', '.join(r['project'])}]" if r["project"] else ""
        note = f" — {r['notes']}" if r["notes"] else ""
        lines.append(f"- {r['task']} (마감 {due}, {r['status']}){proj}{mark}{note}")
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


@tool(
    "notion_add_task",
    "우선순위 트래커에 새 할 일을 추가한다. title 필수, notes/due(YYYY-MM-DD)는 선택.",
    {"title": str, "notes": str, "due": str},
)
async def notion_add_task(args):
    title = (args.get("title") or "").strip()
    if not title:
        return {"content": [{"type": "text", "text": "제목이 비었어요."}]}

    props = {
        "task": {"title": [{"text": {"content": title}}]},
        "Status": {"status": {"name": "Not started"}},
    }
    if (notes := (args.get("notes") or "").strip()):
        props["Notes"] = {"rich_text": [{"text": {"content": notes}}]}
    if (due := (args.get("due") or "").strip()):
        props["Due"] = {"date": {"start": due}}

    try:
        cfg = load_config()
        await _create_page(cfg.tracker_db_id, props)
    except Exception as e:
        return {"content": [{"type": "text", "text": f"[Notion 오류] {e}"}]}
    return {"content": [{"type": "text", "text": f"트래커에 추가함: {title} (Not started)"}]}


@tool(
    "notion_calendar_events",
    "일정 미러 DB(Notion Calendar 와 연결된)에서 다가오는 일정을 가져온다. "
    "오늘/이번 주 '일정·약속·미팅'을 물으면 사용. days(기본 7).",
    {"days": int},
)
async def notion_calendar_events(args):
    cfg = load_config()
    if not cfg.calendar_db_id:
        return {"content": [{"type": "text", "text": "일정 미러 DB가 아직 설정 안 됐어요(NOTION_CALENDAR_DB_ID)."}]}

    days = int(args.get("days") or 7)
    today = dt.date.today()
    until = (today + dt.timedelta(days=days)).isoformat()
    body = {
        "page_size": 100,
        "filter": {"and": [
            {"property": "Date", "date": {"on_or_after": today.isoformat()}},
            {"property": "Date", "date": {"on_or_before": until}},
        ]},
        "sorts": [{"property": "Date", "direction": "ascending"}],
    }
    try:
        results = await _query_db(cfg.calendar_db_id, body)
    except Exception as e:
        return {"content": [{"type": "text", "text": f"[Notion 오류] {e}"}]}

    if not results:
        return {"content": [{"type": "text", "text": f"앞으로 {days}일 등록된 일정이 없어요."}]}

    lines = [f"앞으로 {days}일 일정:"]
    for page in results:
        p = page.get("properties", {})
        # 제목 property 이름은 DB 마다 다를 수 있어 title 타입을 자동 탐색
        title = next((_title(p, k) for k, v in p.items() if v.get("type") == "title"), "") or "(제목 없음)"
        when = _date(p, "Date") or "-"
        lines.append(f"- {when}  {title}")
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}
