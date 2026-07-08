@echo off
rem Run Kuromi (logs to kuromi.log). Use start_kuromi.vbs to run hidden.
set PYTHONUNBUFFERED=1
"C:\Users\admin\kuromi\.venv\Scripts\python.exe" "C:\Users\admin\kuromi\app.py" > "C:\Users\admin\kuromi\kuromi.log" 2>&1
