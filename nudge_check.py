"""능동 마감 체크인: 마감이 임박/지난 할 일이 있을 때만 Slack DM 으로 살짝 찔러준다.

- Claude(Brain)를 부르지 않는다. Notion 트래커를 코드로만 훑는 순수 로직이라 가볍고 안정적.
- 작업 스케줄러가 낮 동안 2~3시간 간격으로 호출한다.
- 스팸 방지: 같은 할 일은 하루에 한 번만 알린다(nudge_state.json). 알릴 게 없으면 조용히 종료.
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
        return json.loads(open(_STATE, encoding="utf-8").read())
    except (OSError, ValueError):
        return {}


def _save_state(state):
    try:
        with open(_STATE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False)
    except OSError:
        pass


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

    # 하루 한 번 규칙: 오늘 이미 알린 제목은 제외.
    state = _load_state()
    if state.get("date") != today.isoformat():
        state = {"date": today.isoformat(), "notified": []}
    already = set(state["notified"])
    fresh = [u for u in urgent if u["title"] not in already]

    if not fresh:
        _log(f"긴급 {len(urgent)}건, 새로 알릴 것 없음 — 조용히 종료")
        return

    slack = AsyncWebClient(token=cfg.slack_bot_token)
    await slack.chat_postMessage(channel=channel, text=format_nudge(fresh))
    state["notified"] = sorted(already | {u["title"] for u in fresh})
    _save_state(state)
    _log(f"{len(fresh)}건 알림 전송")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        _log(f"[실패] {type(e).__name__}: {e}")
        raise
