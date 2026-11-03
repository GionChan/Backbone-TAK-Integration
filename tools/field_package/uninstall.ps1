# Removes the automatic start install.ps1 registered (scheduled task and/or Startup shortcut)
# and stops a running relay. Does not delete this folder.
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $here "lang.ps1")
Import-DeviceEnv (Join-Path $here "device.env")
$system = if ($env:GATEWAY_SYSTEM) { $env:GATEWAY_SYSTEM } else { "tak-relay" }
$taskName = "EFDI-TAK-Relay-$system"

schtasks /Query /TN $taskName > $null 2>&1
if ($LASTEXITCODE -eq 0) {
    schtasks /End /TN $taskName > $null 2>&1
    schtasks /Delete /TN $taskName /F | Out-Null
    Write-Host (T "task_removed" $taskName) -ForegroundColor Green
} else {
    Write-Host (T "task_missing" $taskName) -ForegroundColor Yellow
}

$shortcutPath = Join-Path ([Environment]::GetFolderPath('Startup')) "$taskName.lnk"
if (Test-Path $shortcutPath) {
    Remove-Item $shortcutPath -Force
    Write-Host (T "shortcut_removed" $shortcutPath) -ForegroundColor Green
} else {
    Write-Host (T "shortcut_missing") -ForegroundColor Yellow
}

# run.ps1 restarts the relay 10 s after it exits, so stop the launcher loop first, then python.
Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*run.ps1*" -and $_.CommandLine -like "*$here*" } |
    ForEach-Object {
        Write-Host (T "stopping_loop" $_.ProcessId) -ForegroundColor Yellow
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }

Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*tak_gateway.py*" -and $_.CommandLine -like "*$here*" } |
    ForEach-Object {
        Write-Host (T "stopping_relay" $_.ProcessId) -ForegroundColor Yellow
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }

Write-Host (T "uninstall_done")
exit 0  # do not return the code of a native call above (e.g. "task not found")
