"""Configured local Pakuri collector; public GitHub metadata only."""
import asyncio
import datetime as dt
import json
import sys
from pathlib import Path

from claude_agent_sdk import tool
from config import load_config

_LOCK = asyncio.Lock()
_UTC = dt.timezone.utc


def _timestamp(value):
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=_UTC)
    except (TypeError, ValueError):
        return None


def _read_digest(path):
    if path.stat().st_size > 8_000_000:
        raise ValueError("digest too large")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or not isinstance(data.get("items"), list):
        raise ValueError("unsupported digest")
    return data


async def load_activity(root, days=1, max_results=8):
    """Refresh at most hourly, then return a bounded, dated digest."""
    days = max(1, min(int(days), 14))
    limit = max(1, min(int(max_results), 20))
    root = Path(root).expanduser().resolve()
    digest_path = root / "data" / "latest.json"
    async with _LOCK:
        data = None
        try:
            data = _read_digest(digest_path)
        except (OSError, ValueError, AttributeError):
            pass
        now = dt.datetime.now(_UTC)
        generated = _timestamp(data.get("generated_at")) if data else None
        fresh = (generated and dt.timedelta(0) <= now - generated < dt.timedelta(hours=1)
                 and data.get("window_hours", 24) >= days * 24)
        refresh_error = None
        if not fresh:
            if not (root / "targets.json").is_file() or not (root / "pakuri" / "__main__.py").is_file():
                return {"status": "unavailable", "items": [], "message": "Pakuri 경로·설정을 확인해 주세요."}
            process = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "pakuri", "collect", "--config", "targets.json",
                "--output", "data/latest.json", "--hours", str(days * 24), cwd=str(root),
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            )
            try:
                code = await asyncio.wait_for(process.wait(), timeout=180)
                if code not in (0, 2):
                    refresh_error = "Pakuri 수집 실패"
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                refresh_error = "Pakuri 수집 시간 초과"
            except asyncio.CancelledError:
                if process.returncode is None:
                    process.kill()
                    await process.wait()
                raise
            try:
                data = _read_digest(digest_path)
            except (OSError, ValueError, AttributeError):
                return {"status": "unavailable", "items": [], "message": refresh_error or "Pakuri 결과를 읽지 못했어요."}
        cutoff = now - dt.timedelta(days=days)
        items = []
        for item in data["items"]:
            if not isinstance(item, dict):
                continue
            date = _timestamp(item.get("published_at") or item.get("observed_at"))
            url = str(item.get("url", ""))
            if date is None or not cutoff <= date <= now or not url.startswith("https://github.com/"):
                continue
            items.append(item)
        items.sort(key=lambda x: (bool(x.get("baseline")), -(_timestamp(x.get("published_at") or x.get("observed_at"))).timestamp()))
        return {
            "status": "stale" if refresh_error else data.get("status", "unknown"),
            "generated_at": data.get("generated_at"), "items": items[:limit],
            "window_hours": data.get("window_hours", 24),
            "errors": data.get("errors", []), "coverage": data.get("coverage", []),
            "message": refresh_error,
            "note": "baseline=true는 첫 관측이에요. 신규 변경으로 단정하지 마세요. relevance는 활용 제안이며 사실과 구분하세요.",
        }


@tool(
    "pakuri_activity",
    "Pakuri에서 공개 GitHub 신규 저장소·커밋·릴리스를 확인한다. days(1~14), max_results(1~20). 첫 관측과 새 변경을 구분할 것.",
    {"days": int, "max_results": int},
)
async def pakuri_activity(args):
    root = load_config().pakuri_path
    if not root:
        result = {"status": "unconfigured", "items": [], "message": "PAKURI_PATH가 설정되지 않았어요."}
    else:
        try:
            result = await load_activity(root, args.get("days") or 1, args.get("max_results") or 8)
        except Exception as exc:
            result = {"status": "unavailable", "items": [], "message": f"Pakuri 오류 ({type(exc).__name__})"}
    return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]}
