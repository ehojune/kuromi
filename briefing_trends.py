"""Morning evidence and delivery ledger; on-demand reads never consume news."""
import asyncio
import datetime as dt
import json
import os
from pathlib import Path

from ai_news_tools import collect_ai_news
from pakuri_tools import load_activity

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


async def prepare_trends(cfg, state_path=_STATE):
    tasks = [collect_ai_news(days=7, max_results=30)]
    if cfg.pakuri_path:
        tasks.append(load_activity(cfg.pakuri_path, days=1, max_results=20))
    results = await asyncio.gather(*tasks, return_exceptions=True)
    seen = _load(state_path)
    groups, offered = {}, []
    for kind, result in zip(("ai", "github"), results):
        if isinstance(result, BaseException):
            groups[kind] = {"status": "unavailable", "items": [], "error": type(result).__name__}
            continue
        items = [x for x in result.get("items", []) if _key(kind, x) not in seen]
        items = items[:10 if kind == "ai" else 6]
        groups[kind] = {**result, "items": items}
        offered.extend({"key": _key(kind, x), "url": x.get("url", "")} for x in items)
    return groups, offered


def record_delivery(offered, message, state_path=_STATE):
    """Call only after Slack accepted the message; record links actually included."""
    seen = _load(state_path)
    now = dt.datetime.now(_UTC)
    cutoff = (now - dt.timedelta(days=30)).isoformat()
    seen = {k: v for k, v in seen.items() if isinstance(v, str) and v >= cutoff}
    for item in offered:
        if item["url"] and item["url"] in message:
            seen[item["key"]] = now.isoformat()
    path = Path(state_path)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(seen, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)
