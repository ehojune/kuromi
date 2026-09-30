# Pakuri 브리핑 연결 — 조회용

- `PAKURI_PATH/data/latest.json`을 읽는다. GitHub 수집은 Pakuri 예약 작업이 담당한다.
- 대화 도구 `pakuri_activity`는 결과만 읽으며 수집·발송 기록을 바꾸지 않는다.
- 아침에는 AI 소식을 먼저 작성하고 `post_briefing`에서 Pakuri 결과를 같은 Slack 메시지에 붙인다.
- Slack에서 `브리핑 해줘`를 요청해도 같은 자료를 포함한다. 수동 조회는 이전 발송 항목을 보여주며 발송 기록을 소비하지 않는다.
- 첫 관측·오래된 결과·실패를 구분한다. 같은 저장소는 1건씩, Pakuri는 최대 3건을 표시한다.
- AI와 같은 URL은 반복하지 않는다. Slack이 성공을 확인한 뒤에만 양쪽 발송 기록을 남긴다.
- Pakuri 발송 기록은 프로젝트의 `data/kuromi-delivery.json`, AI 기록은 kuromi의 `briefing_trends_state.json`이다. Git에 넣지 않는다.
- 비공개 추적 명단과 로컬 경로는 공개 kuromi 문서·응답의 진단 정보에 포함하지 않는다.
- 최근 2주는 `data/state.sqlite3`을 읽기 전용으로 조회한다. 공개일 기준이며 초기 수집의 과거 기록도 포함한다. 분야마다 고유 저장소 수를 세고 지정 저장소 태그를 우선한다. 분야는 중복될 수 있다.
- `targets.json`의 검증된 개인 계정을 한국 날짜로 순환한다. 소속은 확인 날짜와 출처를 붙이고 자기소개는 미검증으로 표시한다. 본인 actor 기록과 관련 저장소 push를 구분한다. 전체 추적 명단은 출력하지 않는다.
