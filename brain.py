"""두뇌: Claude Agent SDK 래퍼.

- 커스텀 도구(capture_screen)를 인프로세스 MCP 서버로 물린다.
- llm-wiki 폴더에서 Read/Grep/Glob 만 허용(읽기 전용, 안전).
- Slack 스레드 단위로 대화 세션을 유지한다.
"""
import asyncio

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    TextBlock,
    create_sdk_mcp_server,
)

from google_calendar_tools import (
    google_calendar_add_event,
    google_calendar_delete_event,
    google_calendar_events,
    google_calendar_update_event,
)
from notion_tools import notion_add_task, notion_calendar_events, notion_today_tasks
from paper_tools import (
    add_interest_topic,
    recent_papers_for_interests,
    remove_interest_topic,
    search_pubmed,
)
from persona import build_system_prompt
from tools import capture_screen


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
            client = await self._client(key)
            await client.query(prompt)

            parts: list[str] = []
            async for msg in client.receive_response():
                if isinstance(msg, AssistantMessage):
                    for block in msg.content:
                        if isinstance(block, TextBlock):
                            parts.append(block.text)
            return "".join(parts).strip()

    async def shutdown(self):
        for client in self._clients.values():
            try:
                await client.disconnect()
            except Exception:
                pass
        self._clients.clear()
