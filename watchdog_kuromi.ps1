# 쿠로미(app.py)가 살아 있는지 확인하고, 죽어 있으면 다시 띄운다.
# 예약 작업 KuromiWatchdog 이 9/12/15/18/21시에 호출한다.
# 2026-08-08 에 SDK 버퍼 한계로 크래시한 뒤 3일간 아무도 살리지 않아 만들었다.

$root = 'C:\Users\admin\kuromi'
$log = Join-Path $root 'watchdog.log'
$ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'

function Get-Kuromi {
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -like '*kuromi*app.py*' }
}

function Write-Log($msg) {
    Add-Content -Path $log -Value "$ts $msg" -Encoding utf8
}

$p = Get-Kuromi
if ($p) {
    Write-Log ("정상 (PID " + ($p.ProcessId -join ', ') + ")")
    exit 0
}

# start_kuromi.bat 이 kuromi.log 를 '>' 로 덮어쓴다. 재시작 전에 죽은 이유를 보존한다.
$crashSrc = Join-Path $root 'kuromi.log'
if (Test-Path $crashSrc) {
    Copy-Item $crashSrc (Join-Path $root 'kuromi.crash.log') -Force
    Write-Log '죽어 있음 - kuromi.log 를 kuromi.crash.log 로 보존하고 재시작'
} else {
    Write-Log '죽어 있음 - 재시작'
}

Start-Process wscript -ArgumentList ('"' + (Join-Path $root 'start_kuromi.vbs') + '"')
Start-Sleep -Seconds 15

$q = Get-Kuromi
if ($q) {
    Write-Log ("재시작 성공 (PID " + ($q.ProcessId -join ', ') + ")")
} else {
    Write-Log '재시작 실패 - 확인 필요'
}
