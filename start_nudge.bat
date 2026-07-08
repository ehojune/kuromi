@echo off
rem Run the deadline nudge check once (Task Scheduler calls this every few hours).
rem nudge_check.py writes progress to nudge.log; this redirect is a boot-error backup.
set PYTHONUNBUFFERED=1
"C:\Users\admin\kuromi\.venv\Scripts\python.exe" "C:\Users\admin\kuromi\nudge_check.py" > "C:\Users\admin\kuromi\nudge.boot.log" 2>&1
