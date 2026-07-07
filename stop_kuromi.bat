@echo off
rem 실행 중인 쿠로미(app.py)를 프로세스 트리째 종료한다.
rem /T 로 자식(claude.exe 등)까지 함께 종료 → orphan 방지.
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -like '*kuromi*app.py*' } | ForEach-Object { taskkill /F /T /PID $_.ProcessId 2>$null }"
echo Kuromi stopped (if it was running).
