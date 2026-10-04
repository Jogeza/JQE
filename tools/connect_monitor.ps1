# Paste the Cloudflare connector command into this hidden prompt, never into chat.
$ErrorActionPreference = 'Stop'
$monitorRoot = 'D:\JQE'
$monitorSecret = Read-Host 'Paste the Cloudflare connector command or token' -AsSecureString
$monitorPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($monitorSecret)
try {
    $monitorCommand = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($monitorPointer)
    $monitorToken = ($monitorCommand.Trim() -split '\s+')[-1]
    if ($monitorToken.Length -lt 100 -or $monitorToken -notmatch '^eyJ[A-Za-z0-9_+/=-]+$') {
        throw 'The complete connector token is required. Use Cloudflare Copy; do not copy the shortened text.'
    }
    $monitorDecoded = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($monitorToken)) | ConvertFrom-Json
    if ($monitorDecoded.t -ne '71002a83-abde-4681-966f-e6d88637ead5') {
        throw 'This token belongs to a different tunnel.'
    }
    $monitorTokenPath = Join-Path $monitorRoot 'state\monitor-tunnel.token'
    if (!(Test-Path -LiteralPath $monitorTokenPath)) { New-Item -ItemType File -Path $monitorTokenPath | Out-Null }
    $monitorSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    & icacls $monitorTokenPath /inheritance:r /grant:r "*${monitorSid}:(F)" '*S-1-5-18:(F)' | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Could not restrict token file permissions.' }
    [IO.File]::WriteAllText($monitorTokenPath, $monitorToken)
    Start-Process -FilePath (Join-Path $monitorRoot 'tools\bin\cloudflared.exe') -ArgumentList @('tunnel','--no-autoupdate','run','--token-file',$monitorTokenPath) -WorkingDirectory $monitorRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $monitorRoot 'reports\monitor-setup-20261004\tunnel.stdout.log') -RedirectStandardError (Join-Path $monitorRoot 'reports\monitor-setup-20261004\tunnel.stderr.log')
    Write-Host 'Connector started. Keep this PC running. Ask Codex to verify the connection.'
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($monitorPointer)
    $monitorToken = $null
    $monitorCommand = $null
}
