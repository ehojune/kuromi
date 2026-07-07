@echo off
rem 아침 브리핑 1회 실행 (작업 스케줄러가 08:30 에 호출).
rem 진행 로그는 daily_briefing.py 가 직접 briefing.log 에 쓴다. 여기 리다이렉트는 기동 오류 백업용.
set PYTHONUNBUFFERED=1
"C:\Users\admin\kuromi\.venv\Scripts\python.exe" "C:\Users\admin\kuromi\daily_briefing.py" > "C:\Users\admin\kuromi\briefing.boot.log" 2>&1
