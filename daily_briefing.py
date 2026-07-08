"""아침 브리핑: Notion 트래커 + 최신 논문을 요약해 사용자 Slack DM 으로 보낸다.

Windows 작업 스케줄러가 매일 08:30(꺼져 있었으면 켤 때) 한 번 실행한다.
쿠로미 두뇌(Brain)를 그대로 써서 도구(notion/paper/wiki)로 브리핑을 작성한다.
"""
import asyncio
import datetime as dt
import os
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# 로그는 파이썬이 직접 쓴다 (venv 런처가 쉘 리다이렉트를 자식에 안 넘기는 문제 회피).
_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "briefing.log")


def _log(msg: str) -> None:
    line = f"{dt.datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    print(line, flush=True)
    try:
        with open(_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass

import net  # noqa: F401  (프록시 TLS 대응 — 다른 네트워크 라이브러리보다 먼저)

from slack_sdk.web.async_client import AsyncWebClient

from brain import Brain
from cli import ensure_claude_on_path
from config import load_config
from owner import load_owner

_PROMPT = """지금은 아침이야. 사용자에게 보낼 '오늘의 브리핑'을 Slack 메시지 하나로 만들어줘.

1) 오늘 일정 / 할 일:
   - google_calendar_events 로 다가오는 일정(약속·미팅)을 확인해. (설정 안 됐거나 오류 나면 조용히 건너뛰어.)
   - notion_today_tasks 로 트래커의 오늘·지난 마감과 진행 중인 것을 정리하고,
     오늘 집중하면 좋은 1~3개를 이유와 함께 골라줘.
2) 오늘의 논문: recent_papers_for_interests 를 호출해서 최근 신규 논문 중 눈에 띄는 3~5개만 골라
   왜 볼 만한지 한 줄씩. 관련된 llm-wiki 페이지가 있으면 Grep 으로 찾아 함께 언급해.

말투는 평소 쿠로미대로, 너무 길지 않게 핵심 위주로. 맨 앞에 짧은 인사와 오늘 날짜 한 줄."""


async def main():
    open(_LOG, "w", encoding="utf-8").close()  # 매 실행 로그 새로 시작
    _log("브리핑 시작")
    ensure_claude_on_path()
    cfg = load_config()
    slack = AsyncWebClient(token=cfg.slack_bot_token)

    channel = load_owner().get("channel")
    if not channel and cfg.owner_slack_id:
        opened = await slack.conversations_open(users=cfg.owner_slack_id)
        channel = opened["channel"]["id"]
    if not channel:
        _log("주인 DM 채널을 몰라요. 먼저 Slack 에서 쿠로미에게 DM 을 한 번 보내주세요.")
        return

    # 채널을 구한 뒤부터는 실패해도 조용히 죽지 않고 Slack 으로 알린다.
    try:
        brain = Brain(cfg)
        try:
            _log("두뇌로 브리핑 작성 중...")
            briefing = await brain.ask("daily-briefing", _PROMPT)
        finally:
            await brain.shutdown()

        briefing = briefing or "오늘 브리핑 생성에 실패했어 🥲"
        header = f"🖤 *오늘의 브리핑* ({dt.date.today().isoformat()})\n\n"
        await slack.chat_postMessage(channel=channel, text=header + briefing)
        _log(f"브리핑 전송 완료 (채널 {channel}, {len(briefing)}자)")
    except Exception as e:
        _log(f"[실패] {type(e).__name__}: {e}")
        # 실패 알림 자체가 또 실패해도 무시 (예: Slack 장애).
        try:
            await slack.chat_postMessage(
                channel=channel,
                text=(f"🖤 오늘 아침 브리핑을 만들다 문제가 생겼어: "
                      f"`{type(e).__name__}: {e}`\n(자세한 건 briefing.log 확인해줘)"),
            )
        except Exception:
            pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        _log(f"[실패] {type(e).__name__}: {e}")
        raise
