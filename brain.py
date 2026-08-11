"""두뇌: Claude Agent SDK 래퍼.

- 커스텀 도구(capture_screen)를 인프로세스 MCP 서버로 물린다.
- llm-wiki 폴더에서 Read/Grep/Glob 만 허용(읽기 전용, 안전).
- Slack 스레드 단위로 대화 세션을 유지한다.
"""
import asyncio
import sys
from datetime import datetime

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    TextBlock,
    ToolUseBlock,
    create_sdk_mcp_server,
)

from google_calendar_tools import (
    google_calendar_add_event,
    google_calendar_delete_event,
    google_calendar_events,
    google_calendar_update_event,
)
from notion_tools import (
    notion_add_task,
    notion_calendar_events,
    notion_today_tasks,
    notion_update_task,
)
from paper_tools import (
    add_interest_topic,
    recent_papers_for_interests,
    remove_interest_topic,
    search_pubmed,
)
from persona import build_system_prompt
from tools import capture_screen

# SDK 기본 상한은 1MB 라, 큰 화면 캡처나 큰 파일 Read 한 번에 메시지 리더가 죽고
# 프로세스째 내려갔다(2026-08-08, 3일간 무응답). 넉넉히 잡아 그 낭떠러지를 없앤다.
_MAX_BUFFER_SIZE = 32 * 1024 * 1024

_AUTH_NOTICE = (
    "⚠️ Claude 인증이 풀렸어. 내 답이 아니라 CLI 가 뱉은 상태 메시지야.\n"
    "터미널에서 `claude setup-token` 하고 .env 의 CLAUDE_CODE_OAUTH_TOKEN 을 갱신해줘."
)
_LIMIT_NOTICE = "⚠️ 사용량 한도에 걸렸어. 내 답이 아니라 CLI 상태 메시지야. 한도가 풀리면 다시 답할게."

# CLI 가 인증·한도 문제를 평범한 답변처럼 돌려주는 바람에 그게 쿠로미 말인 척 Slack 에
# 나갔고, 며칠을 눈치 못 챘다(2026-08-07~08). 짧은 답만 검사해 오탐을 막는다.
_STATUS_SIGNS = (
    ("not logged in", _AUTH_NOTICE),
    ("please run /login", _AUTH_NOTICE),
    ("invalid api key", _AUTH_NOTICE),
    ("failed to authenticate", _AUTH_NOTICE),
    ("oauth token has expired", _AUTH_NOTICE),
    ("oauth access token is invalid", _AUTH_NOTICE),
    ("session limit", _LIMIT_NOTICE),
    ("usage limit", _LIMIT_NOTICE),
)
_MAX_STATUS_LEN = 200  # 상태 메시지는 짧다. 이보다 길면 진짜 답변으로 본다.

# 바깥 세계를 바꾸는 도구들. 이게 한 번이라도 불린 뒤에 실패하면 같은 프롬프트를
# 재생하면 안 된다 — 노션 할 일이나 일정이 중복 생성된다.
_WRITE_TOOLS = frozenset({
    "mcp__kuromi__notion_add_task",
    "mcp__kuromi__notion_update_task",
    "mcp__kuromi__google_calendar_add_event",
    "mcp__kuromi__google_calendar_update_event",
    "mcp__kuromi__google_calendar_delete_event",
    "mcp__kuromi__add_interest_topic",
    "mcp__kuromi__remove_interest_topic",
})


def _status_notice(text: str) -> str | None:
    """CLI 상태 메시지를 답변으로 착각하지 않도록 한국어 안내로 바꾼다."""
    if not text or len(text) > _MAX_STATUS_LEN:
        return None
    low = text.lower()
    for sign, notice in _STATUS_SIGNS:
        if sign in low:
            return f"{notice}\n\n(원문: {text.strip()})"
    return None


class Brain:
    def __init__(self, config):
        self.config = config

        server = create_sdk_mcp_server(
            name="kuromi",
            version="1.0.0",
            tools=[
                capture_screen,
                notion_today_tasks,
                notion_add_task,
                notion_update_task,
                notion_calendar_events,
                google_calendar_events,
                google_calendar_add_event,
                google_calendar_update_event,
                google_calendar_delete_event,
                search_pubmed,
                recent_papers_for_interests,
                add_interest_topic,
                remove_interest_topic,
            ],
        )

        self.options = ClaudeAgentOptions(
            system_prompt=build_system_prompt(config.assistant_name, config.wiki_path),
            model=config.model,
            mcp_servers={"kuromi": server},
            # 읽기 전용 파일 도구 + 화면/노션/논문 도구. 파일 쓰기/실행(Write/Edit/Bash)은 제외.
            allowed_tools=[
                "Read", "Grep", "Glob",
                "mcp__kuromi__capture_screen",
                "mcp__kuromi__notion_today_tasks",
                "mcp__kuromi__notion_add_task",
                "mcp__kuromi__notion_update_task",
                "mcp__kuromi__notion_calendar_events",
                "mcp__kuromi__google_calendar_events",
                "mcp__kuromi__google_calendar_add_event",
                "mcp__kuromi__google_calendar_update_event",
                "mcp__kuromi__google_calendar_delete_event",
                "mcp__kuromi__search_pubmed",
                "mcp__kuromi__recent_papers_for_interests",
                "mcp__kuromi__add_interest_topic",
                "mcp__kuromi__remove_interest_topic",
            ],
            permission_mode="bypassPermissions",  # 헤드리스라 승인창이 없음
            cwd=config.wiki_path,                  # 파일 도구 기준 경로 = 위키
            setting_sources=[],                    # 위키의 CLAUDE.md 자동로드 방지(페르소나 보호)
            max_buffer_size=_MAX_BUFFER_SIZE,
        )

        self._clients: dict[str, ClaudeSDKClient] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock(self, key: str) -> asyncio.Lock:
        self._locks.setdefault(key, asyncio.Lock())
        return self._locks[key]

    async def _client(self, key: str) -> ClaudeSDKClient:
        client = self._clients.get(key)
        if client is None:
            client = ClaudeSDKClient(options=self.options)
            await client.connect()
            self._clients[key] = client
        return client

    async def ask(self, key: str, prompt: str) -> str:
        """스레드(key) 컨텍스트를 유지한 채 한 번의 왕복을 처리해 텍스트 답을 반환."""
        async with self._lock(key):
            used: set[str] = set()
            try:
                return await self._round_trip(key, prompt, used)
            except Exception:
                # 리더가 한 번 죽은 클라이언트는 스트림이 닫혀 재사용이 안 된다.
                await self._drop(key)

                # 쓰기 도구가 이미 불렸다면 재생이 위험하다. 실패한 채로 알린다.
                wrote = sorted(used & _WRITE_TOOLS)
                if wrote:
                    raise RuntimeError(
                        "요청 처리 중에 연결이 끊겼어. "
                        f"이미 {', '.join(t.rsplit('__', 1)[-1] for t in wrote)} 를 실행한 뒤라 "
                        "중복 생성될까 봐 다시 시도하지 않았어. 결과를 직접 확인해줘."
                    ) from None

                # 읽기만 했으면 새 세션으로 한 번 재시도(그 스레드의 맥락은 잃는다).
                return await self._round_trip(key, prompt, set())

    async def _round_trip(self, key: str, prompt: str, used: set[str]) -> str:
        client = await self._client(key)
        await client.query(prompt)

        parts: list[str] = []
        async for msg in client.receive_response():
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        parts.append(block.text)
                    elif isinstance(block, ToolUseBlock):
                        # 완료 여부는 알 수 없다. 불린 것만으로 실행된 걸로 보고
                        # 보수적으로 판단한다 — 중복 생성보다 재시도 포기가 낫다.
                        used.add(block.name)

        reply = "".join(parts).strip()
        notice = _status_notice(reply)
        if notice is None:
            return reply

        # 조용히 지나가면 또 며칠을 모른다. 로그에 반드시 남긴다.
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"{stamp} [CLI 상태 메시지] {reply}", file=sys.stderr, flush=True)
        return notice

    async def _drop(self, key: str) -> None:
        client = self._clients.pop(key, None)
        if client is None:
            return
        try:
            await client.disconnect()
        except Exception:
            pass

    async def shutdown(self):
        for client in self._clients.values():
            try:
                await client.disconnect()
            except Exception:
                pass
        self._clients.clear()
