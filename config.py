"""환경설정 로더. .env 를 읽어 Config 로 묶어준다."""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# 실행 위치와 무관하게 이 파일(config.py) 옆의 .env 를 읽는다.
load_dotenv(Path(__file__).resolve().with_name(".env"))


def _get(name: str, default: str | None = None, required: bool = False) -> str:
    val = os.environ.get(name, default)
    if required and not val:
        raise SystemExit(f"[설정 오류] 환경변수 {name} 가 없습니다. .env 를 확인하세요.")
    return val or ""


_HERE = Path(__file__).resolve().parent


@dataclass
class Config:
    slack_bot_token: str      # xoxb-...
    slack_app_token: str      # xapp-... (Socket Mode)
    assistant_name: str
    model: str
    voice_mode: str           # off | local | slack | both
    voice_name: str
    voice_max_chars: int
    wiki_path: str
    # Notion / 브리핑 / 논문
    notion_token: str         # 내부 통합(integration) 토큰
    tracker_db_id: str        # [kobic] 우선순위 트래커 DB id
    calendar_db_id: str       # (선택) Notion Calendar 와 연결된 일정 미러 DB id
    owner_slack_id: str       # (선택) 브리핑 받을 사용자 Slack member id
    ncbi_email: str           # (선택) PubMed 예의용 이메일
    interests_path: str       # 관심사 파일 경로
    google_calendar_credentials_path: str  # (선택) 구글 캘린더 서비스 계정 JSON 키 경로
    google_calendar_id: str                # (선택) 구글 캘린더 ID (본인 Gmail 또는 "primary")
    pakuri_path: str = ""                  # (선택) 공개 GitHub 활동 수집 프로젝트


def load_config() -> Config:
    return Config(
        slack_bot_token=_get("SLACK_BOT_TOKEN", required=True),
        slack_app_token=_get("SLACK_APP_TOKEN", required=True),
        assistant_name=_get("ASSISTANT_NAME", "쿠로미"),
        model=_get("KUROMI_MODEL", "claude-sonnet-5-5"),
        voice_mode=_get("VOICE_MODE", "local").lower(),
        voice_name=_get("VOICE_NAME", "ko-KR-SunHiNeural"),
        voice_max_chars=int(_get("VOICE_MAX_CHARS", "300")),
        wiki_path=_get("LLM_WIKI_PATH", r"C:\Users\admin\llm-wiki"),
        notion_token=_get("NOTION_TOKEN", ""),
        tracker_db_id=_get("NOTION_TRACKER_DB_ID", "9379d5ae-a8a3-4870-9cbd-bdbf046e1248"),
        calendar_db_id=_get("NOTION_CALENDAR_DB_ID", ""),
        owner_slack_id=_get("OWNER_SLACK_ID", ""),
        ncbi_email=_get("NCBI_EMAIL", ""),
        interests_path=_get("INTERESTS_PATH", str(_HERE / "research-interests.md")),
        google_calendar_credentials_path=_get("GOOGLE_CALENDAR_CREDENTIALS_PATH", ""),
        google_calendar_id=_get("GOOGLE_CALENDAR_ID", ""),
        pakuri_path=_get("PAKURI_PATH", ""),
    )
