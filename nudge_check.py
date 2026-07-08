"""능동 마감 체크인: 마감이 임박/지난 할 일이 있을 때만 Slack DM 으로 살짝 찔러준다.

- Claude(Brain)를 부르지 않는다. Notion 트래커를 코드로만 훑는 순수 로직이라 가볍고 안정적.
- 작업 스케줄러(KuromiNudgeCheck)가 09/12/15/18/21시, 즉 깨어있는 시간대에 3시간 간격으로 호출한다.
- 스팸 방지: 하루 1회가 아니라 "완료(Done) 처리될 때까지, 같은 할 일은 최소 ~3시간 간격으로"
  재알림한다(nudge_state.json 에 할 일별 마지막 알림 시각 기록). 그 간격 안이면 조용히 스킵,
  알릴 게 하나도 없으면 Slack 메시지 없이 로그만 남기고 종료.
"""
import asyncio
import datetime as dt
import json
import os
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import net  # noqa: F401  (프록시 TLS — 다른 네트워크 라이브러리보다 먼저)

from slack_sdk.web.async_client import AsyncWebClient

import notion_tools as nt
from config import load_config
from owner import load_owner

_HERE = os.path.dirname(os.path.abspath(__file__))
_STATE = os.path.join(_HERE, "nudge_state.json")
_LOG = os.path.join(_HERE, "nudge.log")

# 스케줄러는 정확히 3시간 간격(09/12/15/18/21시)으로 호출한다. 스케줄 지연/드리프트를
# 견디도록 살짝 여유를 두고, 그보다 조금이라도 더 지났으면 다음 호출 때 재알림한다.
_RENOTIFY_AFTER = dt.timedelta(hours=2, minutes=50)


def _log(msg: str) -> None:
    line = f"{dt.datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    print(line, flush=True)
    try:
        with open(_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def collect_urgent(rows, today):
    """마감이 지났거나(<0) 오늘(0)·내일(1)인 미완료 할 일을 마감 급한 순으로.

    Due 'YYYY-MM-DD' 는 그날 23:59까지를 뜻한다 → 날짜 단위 비교로 충분:
    오늘==마감일이면 delta=0('오늘 마감', 아직 안 지남), 다음날부터 delta<0('지남')."""
    urgent = []
    for page in rows:
        p = page.get("properties", {})
        if nt._status(p) in nt._DONE:
            continue
        due = nt._date(p, "Due")
        if not due:
            continue
        try:
            d = dt.date.fromisoformat(due[:10])
        except ValueError:
            continue
        delta = (d - today).days
        if delta <= 1:
            urgent.append({"title": nt._title(p, "task"), "due": d.isoformat(),
                           "delta": delta, "status": nt._status(p)})
    urgent.sort(key=lambda u: u["delta"])
    return urgent


def format_nudge(urgent):
    lines = ["🖤 마감 체크인!"]
    for u in urgent:
        d = u["delta"]
        tag = f"{-d}일 지남 ⚠️" if d < 0 else ("오늘 마감 🔴" if d == 0 else "내일 마감 🟡")
        lines.append(f"- {u['title']} — {tag} ({u['due']}, {u['status']})")
    return "\n".join(lines)


def _load_state():
    try:
        state = json.loads(open(_STATE, encoding="utf-8").read())
    except (OSError, ValueError):
        return {}
    # 예전 포맷("date"+"notified" 하루 1회 방식) 호환: last_notified 없으면 빈 걸로 시작.
    if "last_notified" not in state:
        return {}
    return state


def _save_state(state):
    try:
        with open(_STATE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False)
    except OSError:
        pass


def pick_fresh(urgent, last_notified, now):
    """last_notified(할 일 제목 -> 마지막 알림 ISO 시각) 기준으로 지금 다시 알릴 것만 골라낸다.

    한 번도 알린 적 없거나, 마지막 알림 후 _RENOTIFY_AFTER 이상 지났으면 재알림 대상."""
    fresh = []
    for u in urgent:
        ts = last_notified.get(u["title"])
        if ts:
            try:
                prev = dt.datetime.fromisoformat(ts)
            except ValueError:
                prev = None
        else:
            prev = None
        if prev is None or (now - prev) >= _RENOTIFY_AFTER:
            fresh.append(u)
    return fresh


async def main():
    cfg = load_config()
    channel = load_owner().get("channel")
    if not channel and cfg.owner_slack_id:
        slack = AsyncWebClient(token=cfg.slack_bot_token)
        opened = await slack.conversations_open(users=cfg.owner_slack_id)
        channel = opened["channel"]["id"]
    if not channel:
        _log("주인 DM 채널 모름 — 종료")
        return

    today = dt.date.today()
    try:
        rows = await nt._query_db(cfg.tracker_db_id)
    except Exception as e:
        _log(f"[Notion 오류] {e}")
        return
    urgent = collect_urgent(rows, today)

    # 완료될 때까지 재알림 규칙: 마지막 알림 후 _RENOTIFY_AFTER 이상 지난 것만 다시 알린다.
    state = _load_state()
    last_notified = state.get("last_notified", {})
    now = dt.datetime.now()
    fresh = pick_fresh(urgent, last_notified, now)

    if not fresh:
        _log(f"긴급 {len(urgent)}건, 재알림 대상 없음(간격 미도달) — 조용히 종료")
        return

    slack = AsyncWebClient(token=cfg.slack_bot_token)
    await slack.chat_postMessage(channel=channel, text=format_nudge(fresh))
    for u in fresh:
        last_notified[u["title"]] = now.isoformat(timespec="seconds")
    # Done 처리되었거나 더 이상 안 급한(연기된) 항목은 상태 파일에서 정리해 무한정 안 늘어나게.
    urgent_titles = {u["title"] for u in urgent}
    state["last_notified"] = {t: ts for t, ts in last_notified.items() if t in urgent_titles}
    _save_state(state)
    _log(f"{len(fresh)}건 알림 전송")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        _log(f"[실패] {type(e).__name__}: {e}")
        raise
