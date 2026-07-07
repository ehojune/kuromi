' Launch Kuromi in the background with NO visible window.
' Used both for auto-start at login and for silent manual start.
CreateObject("WScript.Shell").Run """C:\Users\admin\kuromi\start_kuromi.bat""", 0, False
