@echo off
rem Run the morning briefing once (Task Scheduler calls this at 08:30).
rem daily_briefing.py writes progress to briefing.log; this redirect is a boot-error backup.
set PYTHONUNBUFFERED=1
"C:\Users\admin\kuromi\.venv\Scripts\python.exe" "C:\Users\admin\kuromi\daily_briefing.py" > "C:\Users\admin\kuromi\briefing.boot.log" 2>&1
