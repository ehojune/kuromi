"""쿠로미 — Slack 진입점 (Socket Mode).

- DM(message.im)과 채널 멘션(app_mention)에 응답한다.
- 무거운 처리(Claude 호출)는 백그라운드 태스크로 넘겨 Slack 재전송을 피한다.
- 답을 텍스트로 보내고, VOICE_MODE 에 따라 음성도 낸다.
"""
import asyncio
import re
import socket
import sys

# 한국어 윈도우 콘솔(cp949)에서도 이모지/한글 출력이 죽지 않도록 UTF-8 강제.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import net  # noqa: F401  (프록시 TLS 대응 — 다른 네트워크 라이브러리보다 먼저)

from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_bolt.async_app import AsyncApp

from brain import Brain
from cli import ensure_claude_on_path
from config import load_config
from owner import save_owner
from voice import Voice

config = load_config()
brain = Brain(config)
voice = Voice(config.voice_mode, config.voice_name, config.voice_max_chars)
app = AsyncApp(token=config.slack_bot_token)

_MENTION_RE = re.compile(r"<@[A-Z0-9]+>")
_seen: set[str] = set()  # 이벤트 중복 처리 방지


async def _process(event: dict, client):
    text = _MENTION_RE.sub("", event.get("text", "")).strip()
    if not text:
        return

    channel = event["channel"]
    ts = event["ts"]
    thread_ts = event.get("thread_ts")  # None 이면 최상위(스레드 아님) 메시지

    # 스레드 안에서 온 말이면 그 스레드에, 아니면 채팅창에 바로 답한다.
    reply_thread_ts = thread_ts
    # 대화 맥락 키: 스레드면 스레드별, 아니면 채널(=DM 전체)로 하나의 대화를 이어간다.
    key = f"{channel}:{thread_ts}" if thread_ts else channel

    async def react(name, add=True):
        try:
            fn = client.reactions_add if add else client.reactions_remove
            await fn(channel=channel, timestamp=ts, name=name)
        except Exception:
            pass

    await react("hourglass_flowing_sand", add=True)
    try:
        reply = await brain.ask(key, text)
    except Exception as e:  # 모델/도구 오류를 사용자에게 정직하게
        reply = f"미안, 처리 중에 문제가 생겼어: {e}"
    finally:
        await react("hourglass_flowing_sand", add=False)

    reply = reply or "…(지금은 할 말이 없네)"
    await client.chat_postMessage(channel=channel, thread_ts=reply_thread_ts, text=reply)

    try:
        await voice.speak(reply, slack_client=client, channel=channel, thread_ts=reply_thread_ts)
    except Exception:
        pass  # 음성 실패는 대화를 막지 않는다


def _dispatch(event: dict, client):
    # 빠르게 ack 하고 실제 작업은 백그라운드로.
    uid = event.get("client_msg_id") or f'{event.get("channel")}:{event.get("ts")}'
    if uid in _seen:
        return
    _seen.add(uid)
    if len(_seen) > 2000:
        _seen.clear()
    asyncio.create_task(_process(event, client))


@app.event("app_mention")
async def on_mention(event, client):
    _dispatch(event, client)


@app.event("message")
async def on_message(event, client):
    if event.get("bot_id") or event.get("subtype"):
        return  # 봇/자기 메시지, 편집·삭제 등 무시
    if event.get("channel_type") != "im":
        return  # DM 만 (채널은 멘션으로)
    # 아침 브리핑을 보낼 주인 DM 채널을 기억해 둔다.
    save_owner(event.get("channel", ""), event.get("user", ""))
    _dispatch(event, client)


async def main():
    # 중복 실행 방지: 고정 포트를 잡아 두 번째 인스턴스는 바로 종료.
    global _instance_lock
    _instance_lock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        _instance_lock.bind(("127.0.0.1", 52789))
    except OSError:
        print("이미 쿠로미가 실행 중이에요. 이 인스턴스는 종료합니다.")
        return

    cli = ensure_claude_on_path()
    if cli:
        print(f"claude CLI: {cli}")
    else:
        print("[경고] claude 실행파일을 찾지 못했어요. Claude Code CLI 설치가 필요합니다 (README 참고).")

    handler = AsyncSocketModeHandler(app, config.slack_app_token)
    print(f"🖤 {config.assistant_name} 켜짐. Slack 에서 DM 하거나 멘션해줘. (Ctrl+C 종료)")
    try:
        await handler.start_async()
    finally:
        await brain.shutdown()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🖤 쿠로미 종료.")
