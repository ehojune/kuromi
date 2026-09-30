"""Morning evidence and delivery ledger; on-demand reads never consume news."""
import datetime as dt
import json
import os
import sys
from pathlib import Path

from ai_news_tools import collect_ai_news
from briefing_links import source_urls
from pakuri_tools import post_briefing

_STATE = Path(__file__).with_name("briefing_trends_state.json")
_UTC = dt.timezone.utc


def _load(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _key(kind, item):
    return kind + ":" + str(item.get("canonical_url") or item.get("url") or item.get("id") or "")


async def prepare_trends(cfg, state_path=_STATE, *, include_delivered=False):
    # Pakuri is appended at the confirmed Slack delivery boundary, not by the model.
    try:
        result = await collect_ai_news(days=7, max_results=30)
    except Exception as exc:
        return {"ai": {"status": "unavailable", "items": [], "error": type(exc).__name__}}, []
    seen = {} if include_delivered else _load(state_path)
    items = [x for x in result.get("items", []) if _key("ai", x) not in seen][:10]
    offered = [{"key": _key("ai", x), "url": x.get("url", "")} for x in items]
    return {"ai": {**result, "items": items}}, offered


def record_delivery(offered, message, state_path=_STATE):
    """Call only after Slack accepted the message; record links actually included."""
    seen = _load(state_path)
    now = dt.datetime.now(_UTC)
    cutoff = (now - dt.timedelta(days=30)).isoformat()
    seen = {k: v for k, v in seen.items() if isinstance(v, str) and v >= cutoff}
    urls = source_urls(message)
    for item in offered:
        if item["url"] and item["url"] in urls:
            seen[item["key"]] = now.isoformat()
    path = Path(state_path)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(seen, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


async def deliver_briefing(slack, *, channel, text, offered, project_path="", state_path=_STATE,
                           thread_ts=None, consume=True):
    """One confirmed Slack post owns both the AI and Pakuri delivery ledgers."""
    result = await post_briefing(slack, channel=channel, text=text, project_path=project_path,
                                 thread_ts=thread_ts, consume=consume)
    if not consume:
        return result
    try:
        # Slack's confirmed response includes the final text with the Pakuri appendix.
        outgoing = result.get("message", {}).get("text", text)
        record_delivery(offered, outgoing, state_path)
    except OSError:
        print("[AI 동향] 전송 성공, 발송 기록 저장 실패. 다음 브리핑에서 반복될 수 있음.",
              file=sys.stderr, flush=True)
    return result
