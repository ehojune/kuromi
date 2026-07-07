@echo off
rem 쿠로미 실행 (로그는 kuromi.log 로). 창을 숨기려면 start_kuromi.vbs 를 쓰세요.
set PYTHONUNBUFFERED=1
"C:\Users\admin\kuromi\.venv\Scripts\python.exe" "C:\Users\admin\kuromi\app.py" > "C:\Users\admin\kuromi\kuromi.log" 2>&1
