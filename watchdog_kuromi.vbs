' 감시 스크립트를 창 없이 실행한다. 예약 작업 KuromiWatchdog 이 이 파일을 호출한다.
CreateObject("WScript.Shell").Run _
  "powershell -NoProfile -ExecutionPolicy Bypass -File ""C:\Users\admin\kuromi\watchdog_kuromi.ps1""", 0, False
