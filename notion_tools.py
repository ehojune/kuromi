"""Notion 도구: [kobic] 우선순위 트래커 + 일정 미러 DB 읽기/쓰기.

라이브러리 버전 이슈를 피하려고 Notion REST API(안정 버전 2022-06-28)를 aiohttp 로 직접 호출한다.
TLS 프록시 대응은 net.py(truststore)가 담당 — 이 모듈을 쓰는 프로세스가 먼저 import 할 것.
"""
import datetime as dt
import difflib

import aiohttp

from claude_agent_sdk import tool
from config import load_config

_API = "https://api.notion.com/v1"
_VER = "2022-06-28"
_TIMEOUT = aiohttp.ClientTimeout(total=25)
_DONE = {"Done", "Tentatively done", "over"}  # '완료' 그룹 상태
# 트래커 Status 옵션 (To-do / In progress / Complete 그룹). 완료 처리 기본값은 Done.
_STATUS_OPTIONS = ["waiting", "Not started", "Pending", "In progress",
                   "Blocked", "over", "Tentatively done", "Done"]


def _normalize_status(s: str | None) -> str | None:
    s = (s or "").strip()
    if not s:
        return "Done"  # 그냥 '완료 처리' 요청이면 Done
    for opt in _STATUS_OPTIONS:
        if opt.lower() == s.lower():
            return opt
    m = difflib.get_close_matches(s, _STATUS_OPTIONS, n=1, cutoff=0.6)
    return m[0] if m else None


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


async def _update_page(page_id: str, body: dict) -> dict:
    """페이지 속성/보관 상태를 바꾼다. body 예: {'properties': {...}} 또는 {'archived': True}."""
    async with aiohttp.ClientSession() as s:
        async with s.patch(f"{_API}/pages/{page_id}", headers=_headers(),
                          json=body, timeout=_TIMEOUT) as r:
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


@tool(
    "notion_update_task",
    "우선순위 트래커 할 일의 상태를 바꾼다(완료 처리 등). query(제목 검색어)로 대상을 찾고 "
    "status(기본 'Done')로 바꾼다. notes 로 메모 추가 가능. 정확히 1개로 좁혀질 때만 실행하고 "
    "여러 개면 후보를 돌려주니 더 구체적으로 다시 부를 것. "
    "유효 상태: waiting / Not started / Pending / In progress / Blocked / over / Tentatively done / Done. "
    "사용자가 '~ 끝냈어/완료했어/진행중으로 바꿔줘' 하면 사용.",
    {"query": str, "status": str, "notes": str},
)
async def notion_update_task(args):
    query = (args.get("query") or "").strip()
    if not query:
        return {"content": [{"type": "text", "text": "어떤 할 일인지 query(제목) 를 줘."}]}
    status = _normalize_status(args.get("status"))
    if status is None:
        return {"content": [{"type": "text", "text":
            f"그 상태값을 몰라. 유효한 값: {', '.join(_STATUS_OPTIONS)}"}]}
    notes = (args.get("notes") or "").strip()

    cfg = load_config()
    try:
        rows = await _query_db(cfg.tracker_db_id)
    except Exception as e:
        return {"content": [{"type": "text", "text": f"[Notion 오류] {e}"}]}

    entries = [(_title(p["properties"], "task"), p["id"], _status(p["properties"])) for p in rows]
    # 부분일치 우선, 없으면 difflib 근사매칭.
    cand = [(t, i, s) for t, i, s in entries if query.lower() in t.lower()]
    if not cand:
        close = difflib.get_close_matches(query, [t for t, _, _ in entries], n=5, cutoff=0.4)
        cand = [(t, i, s) for t, i, s in entries if t in close]

    if not cand:
        return {"content": [{"type": "text", "text": f"'{query}' 와 맞는 할 일을 못 찾았어."}]}
    if len(cand) > 1:
        lines = ["여러 개 있어 — 더 구체적으로 말해줘:"] + [f"- {t} ({s})" for t, _, s in cand[:8]]
        return {"content": [{"type": "text", "text": "\n".join(lines)}]}

    title, page_id, old = cand[0]
    props = {"Status": {"status": {"name": status}}}
    if notes:
        props["Notes"] = {"rich_text": [{"text": {"content": notes}}]}
    try:
        await _update_page(page_id, {"properties": props})
    except Exception as e:
        return {"content": [{"type": "text", "text": f"[Notion 오류] {e}"}]}
    return {"content": [{"type": "text", "text": f"'{title}' 상태를 {old} → {status} 로 바꿨어."}]}
