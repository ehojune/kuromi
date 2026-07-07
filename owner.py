"""주인(사용자)의 Slack DM 채널을 기억한다 — 아침 브리핑을 어디로 보낼지 알기 위해.

사용자가 쿠로미에게 DM 을 한 번 보내면 app.py 가 그 채널을 여기 저장하고,
daily_briefing.py 가 그 채널로 브리핑을 보낸다. (별도 설정 불필요)
"""
import json
import os

_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "owner.json")


def load_owner() -> dict:
    try:
        with open(_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_owner(channel: str, user: str) -> None:
    try:
        if load_owner().get("channel") == channel:
            return
        with open(_PATH, "w", encoding="utf-8") as f:
            json.dump({"channel": channel, "user": user}, f)
    except OSError:
        pass
