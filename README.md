# 🖤 쿠로미 — 개인 AI 비서

Neuro-sama 처럼 **Slack** 에서 "쿠로미"라는 이름으로 대화하는 개인 비서.
지금은 이렇게 동작한다:

- **Slack 소통** — DM 하거나 채널에서 멘션하면 답한다 (기본 아바타/이름, 판때기 없음).
- **화면 보기** — "내 화면 봐줘" 하면 스크린샷을 떠서 보고 답한다.
- **지식베이스 참고** — `llm-wiki`(유전체학/유전학 논문 정리)를 읽어 근거 있는 답을 한다.
- **보이스** — 답을 음성으로 읽어준다 (PC 스피커 재생 / Slack 음성파일 업로드).

**나중에 붙일 것** (설계상 자리 마련됨): Notion 업무·일정 관리, 새 논문 브리핑.
**말투·이름·캐릭터·보이스는 언제든 교체 가능** (`persona.py` / `.env`).

---

## 구조

```
사용자 ─(Slack DM/멘션)→ app.py ─→ brain.py ─(Claude Agent SDK)→ Claude
                                        ├─ tools.py    커스텀 도구(화면 캡처) = MCP
                                        ├─ persona.py  성격/말투/역할 = 시스템 프롬프트
                                        └─ llm-wiki    Read/Grep/Glob (읽기 전용)
app.py ─(답변 텍스트)→ Slack
      └(voice.py)→ 음성  PC 스피커 / Slack 업로드
```

두뇌는 **Claude Agent SDK** (Claude Code 와 같은 엔진)라서 **지금 쓰는 Claude 로그인/구독을
그대로 사용**한다. 별도 API 키가 필수는 아니다.

---

## 사전 준비

1. **Python 3.10+** (이 PC 는 3.12 확인됨)
2. **Claude Code CLI** — Agent SDK 가 내부에서 이 실행파일을 띄운다.
   이 PC 에는 Claude 데스크톱 앱에 번들된 `claude.exe` 가 이미 있고,
   `cli.py` 가 그걸 자동으로 찾아 쓰므로 **추가 설치 없이 동작**한다.
   (원한다면 표준 CLI 를 따로 깔아 PATH 에 올려도 된다 — 그러면 그쪽을 우선 사용:
   PowerShell `irm https://claude.ai/install.ps1 | iex`. Node 는 필요 없다.)
   로그인은 이미 되어 있으니 **API 키 없이** 구독 인증을 그대로 쓴다.

## 설치

```bash
cd C:\Users\admin\kuromi
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

---

## Slack 앱 만들기 (한 번만)

1. <https://api.slack.com/apps> → **Create New App** → **From scratch** → 이름/워크스페이스 선택.
2. **Socket Mode** 켜기 → **Basic Information → App-Level Tokens** 에서 토큰 생성
   (scope: `connections:write`) → 이게 `SLACK_APP_TOKEN` (`xapp-...`).
3. **OAuth & Permissions → Bot Token Scopes** 에 추가:
   `app_mentions:read`, `chat:write`, `im:history`, `im:read`, `im:write`,
   `files:write`, `reactions:write` (채널에서도 쓰려면 `channels:history` 도).
4. **Event Subscriptions** 켜기 → **Subscribe to bot events** 에 추가:
   `app_mention`, `message.im`.
5. **Install to Workspace** → 설치 후 **Bot User OAuth Token** 이 `SLACK_BOT_TOKEN` (`xoxb-...`).
6. (선택) **App Home** 에서 *Messages Tab* 을 켜야 DM 을 보낼 수 있다.

## 설정

```bash
copy .env.example .env
```
`.env` 를 열어 채운다:

```ini
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...
ASSISTANT_NAME=쿠로미
VOICE_MODE=local            # off | local | slack | both
VOICE_NAME=ko-KR-SunHiNeural
LLM_WIKI_PATH=C:\Users\admin\llm-wiki
```

## 실행

venv 안의 파이썬으로 실행해야 한다. **주의:** `.venv\Scripts` 폴더 안에 있어도 그냥
`python` 만 치면 시스템 파이썬이 잡혀서 패키지를 못 찾는다. 아래처럼 venv 파이썬을 명시하자.

```powershell
# 방법 1: 전체 경로로 바로 실행 (가장 확실)
C:\Users\admin\kuromi\.venv\Scripts\python.exe C:\Users\admin\kuromi\app.py

# 방법 2: venv 활성화 후 실행
cd C:\Users\admin\kuromi
.\.venv\Scripts\Activate.ps1     # 막히면 방법 1 사용
python app.py
```

`Bolt app is running!` 이 뜨면 연결 성공. 이 창을 켜둔 채로 Slack 에서 쿠로미에게
**DM** 하거나 채널에서 **@쿠로미** 멘션하면 된다. 종료는 `Ctrl+C`.

## 자동 실행 (로그인 시)

윈도우에 로그인하면 쿠로미가 **창 없이 백그라운드로 자동 실행**되도록 설정돼 있다.
- 자동 실행 등록: `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\kuromi.vbs`
  (끄고 싶으면 `Win+R` → `shell:startup` → `kuromi.vbs` 삭제)
- 로그: `kuromi.log` (매 실행마다 새로 씀. 문제 있을 때 여기 확인)
- Task Manager 에 `python.exe` 가 2개 보여도 정상 — venv 런처 + 실제 실행, **봇은 1개**다.
  (중복 실행 방지 장치가 있어 진짜 봇은 항상 하나만 돈다.)

| 하고 싶은 것 | 방법 |
|---|---|
| 지금 켜기 (조용히) | `start_kuromi.vbs` 더블클릭 |
| 지금 켜기 (창 보며) | `start_kuromi.bat` 더블클릭 |
| 끄기 | `stop_kuromi.bat` 더블클릭 |
| 코드/`.env`/persona 수정 반영 | `stop_kuromi.bat` → `start_kuromi.vbs` (재시작) |

---

## 커스터마이즈

| 바꾸고 싶은 것 | 어디 |
|---|---|
| 이름 | `.env` 의 `ASSISTANT_NAME` |
| 말투·성격·역할 | `persona.py` |
| 목소리 | `.env` 의 `VOICE_NAME` (예: `ko-KR-InJoonNeural` 남성) |
| 음성 방식 | `.env` 의 `VOICE_MODE` (`local`=내 PC, `slack`=업로드, `both`, `off`) |
| 모델 | `.env` 의 `KUROMI_MODEL` (비용 낮추려면 `claude-sonnet-5`) |
| 새 도구 추가 | `tools.py` 에 `@tool` 추가 → `brain.py` 의 `allowed_tools` 에 등록 |

한국어 보이스 목록 보기:
```bash
edge-tts --list-voices | findstr ko-KR
```

---

## 일정 브리핑 · 논문 스카우트

매일 아침 **08:30**(PC 가 꺼져 있었으면 켠 뒤 바로) 쿠로미가 DM 으로 브리핑을 보낸다:
1. **오늘 할 일** — Notion [kobic] 우선순위 트래커의 미완료 항목을 마감 순으로 정리 + 오늘 집중할 것 추천
2. **오늘의 논문** — `research-interests.md` 의 주제로 PubMed 최근 논문을 찾아 추천 (관련 위키 있으면 링크)

대화 중에도 "오늘 할 일 뭐야?", "○○ 할일 추가해줘", "이번 주 STR 논문 있어?" 처럼 쓸 수 있다.

**구성 요소**
- `notion_tools.py` — 트래커 읽기(`notion_today_tasks`)/쓰기(`notion_add_task`)
- `paper_tools.py` — PubMed 검색(`search_pubmed`, `recent_papers_for_interests`)
- `research-interests.md` — 논문 검색 주제 (이 파일만 고치면 관심사 변경)
- `daily_briefing.py` — 브리핑 작성 후 DM 전송 (작업 스케줄러 `KuromiDailyBriefing` 가 08:30 실행)
- `net.py` — 회사 TLS 검사 프록시 대응(truststore). Slack/PubMed/Notion HTTPS 통과에 필요

**Notion 연결 (1회 설정)**
1. <https://www.notion.so/my-integrations> → **New integration** (Internal) → 이름 `Kuromi` →
   **Internal Integration Secret**(`ntn_...`) 복사
2. `.env` 의 `NOTION_TOKEN=` 에 붙여넣기
3. Notion 에서 **[kobic] 우선순위 트래커** DB 열기 → 우상단 `•••` → **Connections** → `Kuromi` 추가
4. 재시작(`stop_kuromi.bat` → `start_kuromi.vbs`), Slack 에서 쿠로미에게 DM 한 번(브리핑 보낼 곳 기억용)
5. (선택) `.env` 의 `NCBI_EMAIL` 에 이메일 넣으면 PubMed 예의상 좋음

**참고**
- 일정은 이제 **구글 캘린더를 직접** 읽는다(`google_calendar_events`, 아래 "구글 캘린더 연결" 참고).
  Notion 일정 미러 DB(`notion_calendar_events`)는 예비용으로 남겨뒀지만 기본 브리핑은 구글 캘린더 우선.
- 브리핑 로그: `briefing.log`. 수동 테스트: `start_briefing.vbs` 더블클릭.

**구글 캘린더 연결 (1회 설정, 서비스 계정 방식 — 로그인 갱신 필요 없음)**
1. <https://console.cloud.google.com/> → 프로젝트 생성(또는 기존 것 사용) →
   **API 및 서비스 → 라이브러리** 에서 **Google Calendar API** 사용 설정
2. **API 및 서비스 → 사용자 인증 정보 → 사용자 인증 정보 만들기 → 서비스 계정** 생성
   (이름은 아무거나, 예: `kuromi-calendar`)
3. 만든 서비스 계정 클릭 → **키 → 키 추가 → JSON** → 다운로드된 JSON 파일을
   `kuromi` 폴더 안에 두고(예: `google-calendar-key.json`), `.gitignore` 에 있는지 확인
4. 서비스 계정 이메일 확인 (`...@...iam.gserviceaccount.com` 형태, 콘솔에 표시됨)
5. Google Calendar(캘린더 앱, 또는 calendar.google.com) → 보고 싶은 캘린더 **설정 →
   특정 사용자와 공유** → 위 서비스 계정 이메일을 추가, 권한은 "일정 세부정보 보기"면 충분
6. `.env` 에 추가:
   ```ini
   GOOGLE_CALENDAR_CREDENTIALS_PATH=C:\Users\admin\kuromi\google-calendar-key.json
   GOOGLE_CALENDAR_ID=본인@gmail.com   # 기본 캘린더면 primary 도 가능
   ```
7. `pip install -r requirements.txt` (google-api-python-client, google-auth 추가됨) 후 재시작

## 참고 / 문제 해결

- 쓰기/실행 도구(Write/Edit/Bash)는 일부러 **막아뒀다** — Slack 으로 자율 동작하므로 안전 우선.
  Notion 등 쓰기가 필요해지면 그때 해당 도구만 열어준다.
- 화면 캡처가 "안 보인다"고 하면 Agent SDK/CLI 버전 문제일 수 있다 — 알려주면 파일저장+Read 방식으로 바꿔준다.
- `mss`/`pygame` 는 로컬 데스크톱에서 동작한다. 서버(헤드리스)에선 화면 캡처/로컬재생이 안 되니 `VOICE_MODE=slack`.
