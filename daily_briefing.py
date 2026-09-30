"""아침 브리핑: Notion 트래커 + 최신 논문을 요약해 사용자 Slack DM 으로 보낸다.

Windows 작업 스케줄러가 매일 08:30(꺼져 있었으면 켤 때) 한 번 실행한다.
쿠로미 두뇌(Brain)를 그대로 써서 도구(notion/paper/wiki)로 브리핑을 작성한다.
"""
import asyncio
import datetime as dt
import os
import subprocess
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
from briefing import generate_briefing
from briefing_trends import deliver_briefing


def _refresh_wiki_interests(cfg) -> None:
    """브리핑 전에 llm-wiki 관심사 프로파일(interests.json)을 새로 만든다.
    scan_interests.py 는 외부 의존성이 없어 이 venv 파이썬으로 그대로 돌아간다.
    실패해도 브리핑은 계속 진행한다(직전 interests.json 을 그냥 씀)."""
    script = os.path.join(cfg.wiki_path, "scan_interests.py")
    if not os.path.exists(script):
        _log(f"[관심사] scan_interests.py 없음, 건너뜀: {script}")
        return
    try:
        r = subprocess.run(
            [sys.executable, script],
            cwd=cfg.wiki_path, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=120,
        )
        if r.returncode == 0:
            tail = (r.stdout or "").strip().splitlines()
            _log("[관심사] 갱신 완료: " + (tail[-1] if tail else "ok"))
        else:
            _log(f"[관심사] 갱신 실패(rc={r.returncode}): {(r.stderr or '').strip()[:300]}")
    except Exception as e:
        _log(f"[관심사] 갱신 예외: {type(e).__name__}: {e}")


async def main():
    open(_LOG, "w", encoding="utf-8").close()  # 매 실행 로그 새로 시작
    _log("브리핑 시작")
    ensure_claude_on_path()
    cfg = load_config()
    _refresh_wiki_interests(cfg)  # 위키 관심사 → interests.json 최신화 (브리핑 반영)
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
            briefing, offered = await generate_briefing(brain, cfg, key="daily-briefing")
        finally:
            await brain.shutdown()

        briefing = briefing or "오늘 브리핑 생성에 실패했어 🥲"
        header = f"🖤 *오늘의 브리핑* ({dt.date.today().isoformat()})\n\n"
        await deliver_briefing(slack, channel=channel, text=header + briefing,
                               offered=offered, project_path=cfg.pakuri_path)
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
