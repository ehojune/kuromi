@echo off
rem Stop running Kuromi (app.py) with its whole process tree.
rem /T kills children (claude.exe etc.) too, preventing orphans.
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -like '*kuromi*app.py*' } | ForEach-Object { taskkill /F /T /PID $_.ProcessId 2>$null }"
echo Kuromi stopped (if it was running).
