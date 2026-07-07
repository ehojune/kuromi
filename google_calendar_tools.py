"""Google 캘린더 도구: Notion 미러 없이 구글 캘린더를 직접 읽는다.

서비스 계정(Service Account) 방식 — 사람이 매번 로그인/토큰갱신 할 필요 없이
백그라운드에서 조용히 돌아가는 쿠로미에 맞는 방식이다.

준비물 (README 참고):
1) Google Cloud 프로젝트에서 Calendar API 활성화
2) 서비스 계정 생성 → JSON 키 다운로드 → GOOGLE_CALENDAR_CREDENTIALS_PATH 에 경로 지정
3) 구글 캘린더 설정 → "특정 사용자와 공유" → 서비스 계정 이메일(...iam.gserviceaccount.com) 추가
4) 그 캘린더의 ID(보통 본인 Gmail 주소, 기본 캘린더면 "primary")를 GOOGLE_CALENDAR_ID 에 지정
"""
import asyncio
import datetime as dt

from claude_agent_sdk import tool
from config import load_config

_SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]


def _service():
    # 무거운 google-api 라이브러리는 실제 호출 시점에만 import (구글 캘린더 미설정 환경에서도
    # 나머지 쿠로미 기능이 죽지 않도록).
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    cfg = load_config()
    if not cfg.google_calendar_credentials_path:
        raise RuntimeError("GOOGLE_CALENDAR_CREDENTIALS_PATH 미설정")
    creds = service_account.Credentials.from_service_account_file(
        cfg.google_calendar_credentials_path, scopes=_SCOPES
    )
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def _list_events_sync(calendar_id: str, days: int) -> list:
    service = _service()
    now = dt.datetime.now(dt.timezone.utc)
    until = now + dt.timedelta(days=days)
    result = service.events().list(
        calendarId=calendar_id,
        timeMin=now.isoformat(),
        timeMax=until.isoformat(),
        singleEvents=True,
        orderBy="startTime",
        maxResults=50,
    ).execute()
    return result.get("items", [])


@tool(
    "google_calendar_events",
    "구글 캘린더에서 다가오는 일정을 직접 가져온다(서비스 계정 연동, Notion 미러 거치지 않음). "
    "오늘/이번 주 '일정·약속·미팅'을 물으면 사용. days(기본 7).",
    {"days": int},
)
async def google_calendar_events(args):
    cfg = load_config()
    if not cfg.google_calendar_credentials_path or not cfg.google_calendar_id:
        return {"content": [{"type": "text", "text": (
            "구글 캘린더 연동이 아직 설정 안 됐어요 "
            "(.env 의 GOOGLE_CALENDAR_CREDENTIALS_PATH / GOOGLE_CALENDAR_ID 확인해줘)."
        )}]}

    days = int(args.get("days") or 7)
    try:
        items = await asyncio.to_thread(_list_events_sync, cfg.google_calendar_id, days)
    except Exception as e:
        return {"content": [{"type": "text", "text": f"[Google Calendar 오류] {e}"}]}

    if not items:
        return {"content": [{"type": "text", "text": f"앞으로 {days}일 등록된 일정이 없어요."}]}

    lines = [f"앞으로 {days}일 일정 (Google Calendar):"]
    for ev in items:
        start = ev.get("start", {})
        when = start.get("dateTime") or start.get("date") or "-"
        title = ev.get("summary") or "(제목 없음)"
        loc = ev.get("location")
        line = f"- {when}  {title}"
        if loc:
            line += f" @ {loc}"
        lines.append(line)
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}
