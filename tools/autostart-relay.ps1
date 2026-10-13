# Scheduled-task launcher: starts the verified read-only loopback monitor relay on 127.0.0.1:8766.
# Does not touch API, MT5, supervisor, execution gates or safety state.
$ErrorActionPreference = 'Stop'
$monitorRoot = 'D:\JQE'
$monitorStamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$monitorRelay = Get-NetTCPConnection -State Listen -LocalAddress '127.0.0.1' -LocalPort 8766 -ErrorAction SilentlyContinue
if ($monitorRelay) { Write-Output 'Relay already listening on 127.0.0.1:8766; nothing to start'; exit 0 }
Start-Process -FilePath (Join-Path $monitorRoot 'venv\Scripts\python.exe') -ArgumentList @('-m','tools.start_monitor') -WorkingDirectory $monitorRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $monitorRoot "logs\relay-autostart-$monitorStamp.stdout.log") -RedirectStandardError (Join-Path $monitorRoot "logs\relay-autostart-$monitorStamp.stderr.log")
Write-Output "Relay launcher started; logs relay-autostart-$monitorStamp"
