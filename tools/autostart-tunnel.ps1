# Scheduled-task launcher: starts the Cloudflare tunnel for the protected owner monitor.
# Stdout/stderr are redirected so log evidence survives the non-interactive session.
$ErrorActionPreference = 'Stop'
$monitorRoot = 'D:\JQE'
$monitorStamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$monitorTunnel = Get-CimInstance Win32_Process -Filter "Name = 'cloudflared.exe'" -ErrorAction SilentlyContinue
if ($monitorTunnel) { Write-Output 'cloudflared already running; nothing to start'; exit 0 }
Start-Process -FilePath (Join-Path $monitorRoot 'tools\bin\cloudflared.exe') -ArgumentList @('tunnel','--no-autoupdate','run','--token-file',(Join-Path $monitorRoot 'state\monitor-tunnel.token')) -WorkingDirectory $monitorRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $monitorRoot "logs\tunnel-autostart-$monitorStamp.stdout.log") -RedirectStandardError (Join-Path $monitorRoot "logs\tunnel-autostart-$monitorStamp.stderr.log")
Write-Output "cloudflared launched; logs tunnel-autostart-$monitorStamp"
