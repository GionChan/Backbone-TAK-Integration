# TAK relay launcher: runs the relay in the foreground and restarts it if it stops.
# Normally started by the task or shortcut install.ps1 registers.
# Usage:  .\run.ps1             (reads device.env next to this script)
#         .\run.ps1 -CheckOnly  (preflight with app\doctor.py; does not start the relay)
param(
    [string]$Python = "python",
    [switch]$CheckOnly
)
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here
. (Join-Path $here "lang.ps1")

$envFile = Join-Path $here "device.env"
if (-not (Test-Path $envFile)) {
    Write-Host (T "no_env") -ForegroundColor Red
    exit 1
}
Import-DeviceEnv $envFile

. (Join-Path $here "bootstrap.ps1")

if ($CheckOnly) {
    & $VenvPython (Join-Path $here "app\doctor.py")
    exit $LASTEXITCODE
}

New-Item -ItemType Directory -Force -Path (Join-Path $here "logs") | Out-Null

while ($true) {
    $log = Join-Path $here ("logs\relay-{0}.log" -f (Get-Date -Format "yyyyMMdd"))
    Write-Host (T "starting" (Get-Date -Format "HH:mm:ss") $log)
    & $VenvPython -u (Join-Path $here "app\tak_gateway.py") 2>&1 |
        ForEach-Object { $line = "$_"; $line | Out-File -FilePath $log -Append -Encoding utf8; $line }
    Write-Host (T "stopped" (Get-Date -Format "HH:mm:ss") $LASTEXITCODE) -ForegroundColor Yellow
    Start-Sleep -Seconds 10
}
