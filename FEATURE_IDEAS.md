# 쿠로미 기능 아이디어 노트

2026-07-08 밤, 오빠가 잠든 사이 쿠로미가 정리함. 지금 아키텍처(Slack + Claude Agent SDK +
Notion + PubMed + llm-wiki + 화면캡처 + 음성, 읽기전용 파일도구)를 그대로 살려서 얹을 수
있는 것들 위주로 골랐다. 우선순위/구현 난이도는 주관적 추정이니 참고만.

---

## 1. 할 일 완료·상태 갱신 (notion_update_task)
**왜**: 지금은 `notion_add_task`(추가)만 있고, "K-Cluster 확인 끝냈어" 처럼 말해도 트래커
Status를 못 바꾼다. 매번 Notion 앱 열어야 함.

**구현 방식**:
- `notion_tools.py`에 `notion_update_task(title_query, new_status, notes?)` 도구 추가.
- 트래커 DB `_query_db` 로 전체 가져온 뒤 `difflib.get_close_matches` 로 제목 퍼지매칭.
  - 매치 1개면 바로 `PATCH /pages/{id}` (Notion REST, `_create_page`처럼 aiohttp 직접 호출)
    로 Status 갱신.
  - 매치 여러 개/0개면 "어떤 거? 후보: A/B/C" 형태로 되물어보게 텍스트만 반환(모델이 다음
    턴에 정확한 title로 재호출).
- 난이도: 낮음 (기존 `_query_db`/`_headers` 재사용, 반나절 작업).

## 2. 구글 캘린더 일정 등록 (google_calendar_add_event)
**왜**: 방금 읽기(`google_calendar_events`)는 붙였는데, "내일 3시에 미팅 잡아줘" 는 아직 못 함.
읽기/쓰기가 같이 있어야 진짜 비서스러움.

**구현 방식**:
- `google_calendar_tools.py`에 스코프를 `calendar.readonly` → `calendar.events`(쓰기 포함)로
  넓히고, `service.events().insert(...)` 호출하는 도구 추가.
- 입력: title, start(ISO), end(ISO, 없으면 +1시간), location?.
- 안전장치: 삭제/수정은 아직 안 만듦(추가만) — 잘못 지우는 사고 방지.
- 난이도: 낮음 (이미 서비스 계정 인증 코드 있음, 스코프+메서드만 추가).

## 3. 능동 체크인 (하루 1번 말고, 필요할 때만)
**왜**: 지금은 08:30 브리핑 한 번뿐. "클로드 AI for science 마감 7/14" 같은 급한 건
당일까지 조용히 묻힐 수 있음.

**구현 방식**:
- `daily_briefing.py` 를 참고한 `nudge_check.py` 를 새로 만들어 Windows 작업 스케줄러에
  2~3시간 간격 트리거 추가.
- 이 스크립트는 브리핑처럼 Claude를 매번 부르지 않고, `notion_today_tasks` 결과를 코드로만
  훑어서 "오늘 마감" 또는 "마감 1일 전"인 게 있을 때만 짧은 DM ("~ 오늘 마감이야!") 전송.
  없으면 조용히 종료 (스팸 방지가 핵심).
- 난이도: 낮음~중간 (새 스크립트 하나, Claude 호출 없이 순수 로직이라 오히려 가볍고 안정적).

## 4. 위키 자동 편입 파이프라인 (wiki_add_source)
**왜**: 지금 llm-wiki 갱신은 수동(PDF 주면 사람이 정리). Read/Grep/Glob만 허용된 안전 설계를
깨지 않으면서, 논문 한 편 편입 과정만 반자동화하면 좋을 것.

**구현 방식**:
- 범용 Write 도구를 여는 대신, **경로가 wiki_path 하위로 고정된 전용 도구**를 새로 만든다
  (`wiki_tools.py`): `wiki_add_source(pdf_path, title)` → `pypdf`로 텍스트 추출 →
  Claude가 이미 대화 중이니 그 요약을 그대로 `sources/`, `wiki/` 밑에 정해진 템플릿으로 저장.
- `brain.py` allowed_tools 에 이 도구 하나만 추가로 열어주면 됨 (Write/Edit는 여전히 막힌 채).
- 위험 요소: 경로 escape 방지(항상 `wiki_path` 하위인지 검증), 기존 파일 덮어쓰기 방지.
- 난이도: 중간 (PDF 파싱 품질, 기존 위키 포맷 컨벤션 파악 필요 — llm-wiki 구조 먼저 조사해야 함).

## 5. 짧은 장기 기억 (kuromi-memory.md)
**왜**: 지금 대화 맥락은 Slack 스레드/채널 단위로만 유지되고(`brain.py`의 `_clients` 딕셔너리),
쿠로미를 껐다 켜거나 새 대화를 시작하면 "오빠가 전에 말한 선호"가 다 날아감. 지금 이 llm-wiki
세션엔 MEMORY.md 같은 장기 기억이 있는데 쿠로미 쪽엔 없음.

**구현 방식**:
- `kuromi-memory.md` 파일 하나 만들고, `persona.py`의 시스템 프롬프트에 그 내용을 주입
  (wiki_path 처럼 config로 경로 전달).
- `memory_update(note)` 도구를 하나 추가해서 "이건 기억해둬" 류 요청 시 파일에 한 줄 append.
- 브리핑/평소 대화 모두 같은 Brain 인스턴스라 자연히 공유됨.
- 난이도: 낮음 (research-interests.md 관리 패턴 그대로 재사용 가능 — `paper_tools.py`의
  add/remove_interest_topic 이미 비슷한 구조).

## 6. Cinnamoroll (Claude Science 대체/보완)
**왜**: 아래 별도 조사 참고 — Claude Science 앱 자체는 Windows 미지원이라 이 세션에 바로
서브에이전트로 못 붙임. 대신 Claude Code/쿠로미에 "Agent Skills" 형태로 과학 스킬 세트를
얹으면 비슷한 효과를 낼 수 있음.

**구현 방식(제안, 아직 미실행 — 신뢰 검토 필요)**:
- `K-Dense-AI/scientific-agent-skills` (GitHub, Claude Code 호환 명시) 같은 오픈 Agent
  Skills 라이브러리를 검토 후, 필요한 스킬만 골라 `.claude/skills/` 밑에 설치.
- 이 llm-wiki 프로젝트 혹은 kuromi 쪽에 `cinnamoroll` 이라는 이름의 서브에이전트 정의
  (`.claude/agents/cinnamoroll.md`)를 만들어, 유전체/STR/스플라이싱 분석용 스킬 세트를
  두르게 하면 "Agent(subagent_type: cinnamoroll)"로 부를 수 있음.
- **주의**: 제3자 스킬 코드는 임의 스크립트를 포함할 수 있어 보안 검토 없이 설치하면 안 됨 —
  오빠 확인 먼저 받고 진행하는 게 맞다고 판단해서 이번엔 설치까지는 안 함.

## 7. 브리핑 실패 시 조용히 죽지 않기
**왜**: `daily_briefing.py`가 실패하면 지금은 `briefing.log`에만 남고 Slack으론 아무 말도
없어서, 오빠가 로그를 직접 열어보기 전엔 "오늘 브리핑이 안 온 이유"를 모름.

**구현 방식**:
- `main()`의 `except Exception` 블록에서 재발생(`raise`) 전에 `slack.chat_postMessage`로
  "브리핑 만들다 문제 생겼어: {e}" 한 줄 보내기 (channel 은 이미 위에서 구해둔 값 재사용).
- 난이도: 아주 낮음 (몇 줄 추가).

---

## 추천 순서 (체감 가치 대비 난이도)
1. **#7 브리핑 실패 알림** — 5분 작업, 안정성 직결
2. **#1 할 일 완료 처리** — 매일 쓰는 기능이라 체감 가장 큼
3. **#3 능동 체크인** — 마감 놓치는 것 방지, Claude 호출 없어 가벼움
4. **#2 캘린더 쓰기** — 방금 붙인 읽기 기능의 자연스러운 확장
5. **#5 장기 기억** — 대화 품질 개선
6. **#4 위키 파이프라인** — 가치 크지만 llm-wiki 컨벤션 파악부터 필요해 가장 오래 걸림
7. **#6 Cinnamoroll** — 오빠 승인 먼저 필요 (제3자 코드 신뢰 문제)

원하는 거 골라서 "이거 만들어줘" 하면 바로 들어갈게.
