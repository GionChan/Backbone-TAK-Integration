# TAK relay installer.
#   1. language (fi / en)   2. mode (direct / local network / TAK Server)   3. mode questions
#   4. dependencies   5. automatic start   6. start now and check /status   7. what to set in TAK
# Choices are saved in device.env; a choice already there is not asked again.
#
# Usage:  install.cmd                       (asks)
#         .\install.ps1 -Lang en -Mode server  (no questions for what is given)
#         .\install.ps1 -AtSystemStartup    (start at boot before sign-in; needs admin, runs as SYSTEM)
param(
    [string]$Python = "python",
    # No [ValidateSet] here: PowerShell would also validate the later assignments below
    # (e.g. an empty value read from device.env) and stop the installer.
    [string]$Lang = "",
    [string]$Mode = "",
    [switch]$AtSystemStartup
)
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here

# Files from a downloaded zip carry "Mark of the Web", which blocks them by default.
Get-ChildItem $here -Include *.ps1, *.cmd -Recurse | ForEach-Object {
    try { Unblock-File -Path $_.FullName -ErrorAction SilentlyContinue } catch {}
}
. (Join-Path $here "lang.ps1")

if ($Lang -and $Lang -notin @("fi", "en")) { Write-Host "-Lang: fi | en" -ForegroundColor Red; exit 1 }
if ($Mode -and $Mode -notin @("direct", "multicast", "server")) {
    Write-Host "-Mode: direct | multicast | server" -ForegroundColor Red; exit 1
}

$envFile = Join-Path $here "device.env"
if (-not (Test-Path $envFile)) {
    Write-Host "device.env puuttuu / is missing: make_relay_package.py" -ForegroundColor Red
    exit 1
}

function Set-EnvValue([string]$Key, [string]$Value) {
    # Replaces "KEY=..." or "# KEY=..." in device.env, else appends.
    $lines = @(Get-Content $envFile)
    $done = $false
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match "^\s*#?\s*$Key\s*=") { $lines[$i] = "$Key=$Value"; $done = $true; break }
    }
    if (-not $done) { $lines += "$Key=$Value" }
    Set-Content -Path $envFile -Value $lines -Encoding UTF8
    Set-Item -Path "Env:$Key" -Value $Value
}

function Read-Choice([string[]]$Valid) {
    while ($true) {
        $a = "$(Read-Host (T 'choice'))".Trim()
        if ($Valid -contains $a) { return $a }
        Write-Host (T "invalid") -ForegroundColor Yellow
    }
}

function Read-Value([string]$Prompt, [string]$Default = "") {
    $shown = if ($Default) { "$Prompt [$Default]" } else { $Prompt }
    $a = "$(Read-Host $shown)".Trim()
    if ($a) { return $a }
    return $Default
}

function Read-File([string]$Prompt, [string]$Default) {
    while ($true) {
        $path = Read-Value $Prompt $Default
        if ($path -and (Test-Path $path -PathType Leaf)) { return $path }
        Write-Host (T "srv_missing_file" $path) -ForegroundColor Yellow
    }
}

$cfg = Read-DeviceEnv $envFile
foreach ($k in $cfg.Keys) { Set-Item -Path "Env:$k" -Value $cfg[$k] }

# ---- 1. language
if (-not $Lang) { $Lang = $cfg["RELAY_LANG"] }
if ($Lang -notin @("fi", "en")) {
    Write-Host ""
    Write-Host "Valitse kieli / Choose language"
    Write-Host "  1) Suomi"
    Write-Host "  2) English"
    while ($true) {
        $a = "$(Read-Host 'Valinta / Choice')".Trim()
        if ($a -eq "1") { $Lang = "fi"; break }
        if ($a -eq "2") { $Lang = "en"; break }
    }
}
Set-EnvValue "RELAY_LANG" $Lang
Write-Host ""
Write-Host (T "title") -ForegroundColor Cyan

# ---- 2. mode
if (-not $Mode) { $Mode = $cfg["TAK_MODE"] }
if ($Mode -notin @("direct", "multicast", "server")) {
    Write-Host ""
    Write-Host (T "mode_title")
    Write-Host (T "mode_1")
    Write-Host (T "mode_2")
    Write-Host (T "mode_3")
    $Mode = @{ "1" = "direct"; "2" = "multicast"; "3" = "server" }[(Read-Choice @("1", "2", "3"))]
}
Set-EnvValue "TAK_MODE" $Mode
Write-Host (T "mode_set" (T "mode_$Mode")) -ForegroundColor Green

# ---- 3. questions for the mode
if ($Mode -eq "server") {
    Write-Host (T "srv_hint")
    if (-not $env:TAK_SERVER) {
        $srv = ""
        while (-not $srv) { $srv = Read-Value (T "srv_address") }
        Set-EnvValue "TAK_SERVER" $srv
    }
    $p12s = @(Get-ChildItem (Join-Path $here "certs\tak") -Filter *.p12 -ErrorAction SilentlyContinue)
    $trustGuess = ($p12s | Where-Object { $_.Name -match "trust" } | Select-Object -First 1)
    $clientGuess = ($p12s | Where-Object { $_.Name -notmatch "trust" } | Select-Object -First 1)
    if (-not $env:TAK_SERVER_P12) {
        $default = if ($clientGuess) { "certs\tak\$($clientGuess.Name)" } else { "" }
        Set-EnvValue "TAK_SERVER_P12" (Read-File (T "srv_p12") $default)
    }
    if (-not $env:TAK_SERVER_TRUST_P12) {
        $default = if ($trustGuess) { "certs\tak\$($trustGuess.Name)" } else { "" }
        Set-EnvValue "TAK_SERVER_TRUST_P12" (Read-File (T "srv_trust") $default)
    }
    if (-not $env:TAK_SERVER_P12_PASSWORD) {
        $secure = Read-Host (T "srv_password") -AsSecureString
        $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
        try { $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) }
        finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
        Set-EnvValue "TAK_SERVER_P12_PASSWORD" $plain
    }
}
if ($Mode -eq "multicast") {
    Write-Host (T "mc_warning") -ForegroundColor Yellow
    if ($env:TAK_INGEST -eq "1" -and -not $env:TAK_INGEST_UIDS) {
        $uids = Read-Value (T "mc_uids")
        if ($uids) { Set-EnvValue "TAK_INGEST_UIDS" $uids }
    }
}

# ---- 4. dependencies
. (Join-Path $here "bootstrap.ps1")
Write-Host (T "deps_ok") -ForegroundColor Green

# ---- 5. automatic start
$system = if ($env:GATEWAY_SYSTEM) { $env:GATEWAY_SYSTEM } else { "tak-relay" }
$httpPort = if ($env:GATEWAY_HTTP_PORT) { $env:GATEWAY_HTTP_PORT } else { "8088" }
$taskName = "EFDI-TAK-Relay-$system"
$runPs1 = Join-Path $here "run.ps1"
$action = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$runPs1`""

schtasks /Query /TN $taskName > $null 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host (T "removing_old_task" $taskName) -ForegroundColor Yellow
    schtasks /Delete /TN $taskName /F > $null 2>&1
}

# Preferred: Task Scheduler. Some locked-down accounts may not create even their own ONLOGON
# task; then fall back to a Startup-folder shortcut, which needs no special rights.
$method = $null
if ($AtSystemStartup) {
    Write-Host (T "task_system") -ForegroundColor Cyan
    schtasks /Create /TN $taskName /TR $action /SC ONSTART /RU SYSTEM /RL HIGHEST /F 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { $method = "task" }
} else {
    Write-Host (T "task_logon") -ForegroundColor Cyan
    schtasks /Create /TN $taskName /TR $action /SC ONLOGON /RL LIMITED /F 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { $method = "task" }
}

$startupDir = [Environment]::GetFolderPath('Startup')
$shortcutPath = Join-Path $startupDir "$taskName.lnk"
if (-not $method) {
    if ($AtSystemStartup) {
        Write-Host (T "task_system_failed") -ForegroundColor Red
        exit 1
    }
    Write-Host (T "task_fallback") -ForegroundColor Yellow
    $wsh = New-Object -ComObject WScript.Shell
    $sc = $wsh.CreateShortcut($shortcutPath)
    $sc.TargetPath = "powershell.exe"
    $sc.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$runPs1`""
    $sc.WorkingDirectory = $here
    $sc.WindowStyle = 7
    $sc.Save()
    $method = "startup"
    Write-Host (T "shortcut_made" $shortcutPath) -ForegroundColor Green
}

# ---- 6. start now and check
Write-Host (T "starting_now") -ForegroundColor Cyan
if ($method -eq "task") {
    schtasks /Run /TN $taskName | Out-Null
} else {
    Start-Process -FilePath "powershell.exe" -WorkingDirectory $here -WindowStyle Hidden `
        -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File", "`"$runPs1`""
}

Write-Host (T "waiting") -ForegroundColor Cyan
Start-Sleep -Seconds 6
$statusUrl = "http://127.0.0.1:$httpPort/"
try {
    $status = Invoke-RestMethod -Uri "http://127.0.0.1:$httpPort/status" -TimeoutSec 5
    if ($status.healthy) {
        Write-Host (T "healthy") -ForegroundColor Green
    } else {
        Write-Host (T "not_healthy" ($status.reasons -join ", ")) -ForegroundColor Yellow
        Write-Host (T "not_healthy_hint") -ForegroundColor Yellow
    }
} catch {
    Write-Host (T "no_answer" $httpPort) -ForegroundColor Yellow
}

# ---- 7. what to set in TAK
Write-Host ""
Write-Host (T "done") -ForegroundColor Green
if ($method -eq "task") { Write-Host (T "autostart_task" $taskName) } else { Write-Host (T "autostart_startup" $shortcutPath) }
Write-Host (T "restart_note")
Write-Host ""
Write-Host (T "next_title") -ForegroundColor Cyan
switch ($Mode) {
    "direct" {
        $udp = if ($env:TAK_UDP_PORT) { $env:TAK_UDP_PORT } else { "6969" }
        $tcp = if ($env:TAK_PORT) { $env:TAK_PORT } else { "8087" }
        Write-Host (T "next_direct" $udp $tcp)
        if ($env:TAK_INGEST -eq "1" -and $env:TAK_UDP_IN_PORT) { Write-Host (T "next_direct_pli" $env:TAK_UDP_IN_PORT) }
    }
    "multicast" {
        $group = if ($env:TAK_MULTICAST_GROUP) { $env:TAK_MULTICAST_GROUP } else { "239.2.3.1:6969" }
        Write-Host (T "next_multicast" $group)
    }
    "server" { Write-Host (T "next_server") }
}
Write-Host ""
Write-Host (T "status_page" $statusUrl)
Write-Host (T "doctor_hint")
Write-Host (T "uninstall_hint")
# The install succeeded even if an intermediate native call (e.g. a failed schtasks attempt)
# left $LASTEXITCODE non-zero; return 0 so install.cmd does not report failure.
exit 0
