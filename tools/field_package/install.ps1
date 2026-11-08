# TAK relay installer.
#   1. language (fi / en)   2. certificate bundle and device name (template package only)
#   3. mode (direct / local network / TAK Server) and its questions, sharing markers   4. dependencies
#   5. automatic start   6. start now and check /status   7. what to set in TAK
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

function Stop-AfterTries([int]$Try) {
    # Read-Host returns "" forever once input ends; never loop without end.
    if ($Try -ge 10) { Write-Host (T "too_many_tries") -ForegroundColor Red; exit 1 }
}

function Read-Choice([string[]]$Valid) {
    for ($try = 1; ; $try++) {
        $a = "$(Read-Host (T 'choice'))".Trim()
        if ($Valid -contains $a) { return $a }
        Write-Host (T "invalid") -ForegroundColor Yellow
        Stop-AfterTries $try
    }
}

function Read-Value([string]$Prompt, [string]$Default = "") {
    $shown = if ($Default) { "$Prompt [$Default]" } else { $Prompt }
    $a = "$(Read-Host $shown)".Trim()
    if ($a) { return $a }
    return $Default
}

function Read-File([string]$Prompt, [string]$Default) {
    for ($try = 1; ; $try++) {
        $path = (Read-Value $Prompt $Default).Trim('"')
        if ($path -and (Test-Path $path -PathType Leaf)) { return $path }
        Write-Host (T "srv_missing_file" $path) -ForegroundColor Yellow
        Stop-AfterTries $try
    }
}

function Find-Bundle([string]$Dir) {
    # Exactly one <slot>-cert.pem with its -key.pem under $Dir, plus a CA -> hashtable, else $null.
    $pairs = @(Get-ChildItem $Dir -Recurse -Filter "*-cert.pem" -ErrorAction SilentlyContinue |
            Where-Object { Test-Path ($_.FullName -replace '-cert\.pem$', '-key.pem') })
    if ($pairs.Count -ne 1) { return $null }
    $folder = $pairs[0].DirectoryName
    $ca = Join-Path $folder "efdi-ca-root.pem"
    if (-not (Test-Path $ca)) {
        $ca = @(Get-ChildItem $folder -Filter *.pem | Where-Object { $_.Name -notmatch 'cert|key' } |
                Select-Object -First 1 | ForEach-Object { $_.FullName })[0]
    }
    if (-not $ca) { return $null }
    return @{ cert = $pairs[0].FullName; key = ($pairs[0].FullName -replace '-cert\.pem$', '-key.pem');
              ca = $ca; notes = (Join-Path $folder "NOTES.md"); tmp = $null }
}

function Open-Bundle([string]$Path) {
    # A folder, or a .zip / .tar.gz unpacked to a temporary folder (removed after copying).
    if (Test-Path $Path -PathType Container) { return Find-Bundle $Path }
    if (-not (Test-Path $Path -PathType Leaf)) { return $null }
    $tmp = Join-Path ([IO.Path]::GetTempPath()) ("efdi-bundle-" + [guid]::NewGuid())
    New-Item -ItemType Directory $tmp | Out-Null
    try {
        if ($Path -match '\.zip$') { Expand-Archive -Path $Path -DestinationPath $tmp }
        elseif ($Path -match '\.(tar\.gz|tgz)$') { tar -xzf $Path -C $tmp }
    } catch {}
    $b = Find-Bundle $tmp
    if ($b) { $b.tmp = $tmp } else { Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue }
    return $b
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
    for ($try = 1; ; $try++) {
        $a = "$(Read-Host 'Valinta / Choice')".Trim()
        if ($a -eq "1") { $Lang = "fi"; break }
        if ($a -eq "2") { $Lang = "en"; break }
        if ($try -ge 10) { Write-Host "Liian monta virheellistä vastausta / Too many invalid answers." -ForegroundColor Red; exit 1 }
    }
}
Set-EnvValue "RELAY_LANG" $Lang
Write-Host ""
Write-Host (T "title") -ForegroundColor Cyan

# ---- 2. certificate bundle and device name (a template package has neither)
$certDir = Join-Path $here "certs"
if (-not (Find-Bundle $certDir)) {
    Write-Host ""
    Write-Host (T "bundle_title")
    $downloads = Join-Path $env:USERPROFILE "Downloads"
    $default = @(Get-ChildItem $downloads -Filter "efdi-onboarding*" -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1 | ForEach-Object { $_.FullName })[0]
    for ($try = 1; ; $try++) {
        $path = (Read-Value (T "bundle_prompt") $default).Trim('"')
        $bundle = if ($path) { Open-Bundle $path } else { $null }
        if ($bundle) { break }
        Write-Host (T "bundle_bad" $path) -ForegroundColor Yellow
        Stop-AfterTries $try
    }
    New-Item -ItemType Directory $certDir -Force | Out-Null
    Copy-Item -Path @($bundle.cert, $bundle.key) -Destination $certDir
    Copy-Item -Path $bundle.ca -Destination (Join-Path $certDir "efdi-ca-root.pem")
    if (Test-Path $bundle.notes) { Copy-Item -Path $bundle.notes -Destination $certDir }
    if ($bundle.tmp) { Remove-Item -Recurse -Force $bundle.tmp -ErrorAction SilentlyContinue }
    Write-Host (T "bundle_copied" (Split-Path $bundle.cert -Leaf)) -ForegroundColor Green
}
if (-not $env:GATEWAY_SYSTEM) {
    Write-Host ""
    Write-Host (T "system_note")
    $default = ("tak-relay-" + "$env:COMPUTERNAME".ToLower()) -replace '[^a-z0-9-]', '-'
    for ($try = 1; ; $try++) {
        $name = Read-Value (T "system_prompt") $default
        if ($name -cmatch '^[a-z0-9][a-z0-9-]{2,62}$') { break }
        Write-Host (T "system_bad") -ForegroundColor Yellow
        Stop-AfterTries $try
    }
    Set-EnvValue "GATEWAY_SYSTEM" $name
}

# ---- 3. mode
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

# ---- sharing markers and drawings (off or on; device.env keeps the answer)
if ($env:TAK_SHARE_MARKERS -notin @("0", "1")) {
    Write-Host ""
    Write-Host (T "share_title")
    Write-Host (T "share_1")
    Write-Host (T "share_2")
    Set-EnvValue "TAK_SHARE_MARKERS" (@{ "1" = "0"; "2" = "1" }[(Read-Choice @("1", "2"))])
}
Write-Host (T "share_set_$($env:TAK_SHARE_MARKERS)") -ForegroundColor Green

# ---- questions for the mode
if ($Mode -eq "server") {
    Write-Host (T "srv_hint")
    if (-not $env:TAK_SERVER) {
        $srv = ""
        for ($try = 1; -not $srv; $try++) {
            $srv = Read-Value (T "srv_address")
            if (-not $srv) { Stop-AfterTries $try }
        }
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
    if (($env:TAK_INGEST -eq "1" -or $env:TAK_SHARE_MARKERS -eq "1") -and -not $env:TAK_INGEST_UIDS) {
        $uids = Read-Value (T "mc_uids")
        if ($uids) { Set-EnvValue "TAK_INGEST_UIDS" $uids }
    }
}

# ---- 4. dependencies
. (Join-Path $here "bootstrap.ps1")
Write-Host (T "deps_ok") -ForegroundColor Green

# ---- permissions: the folder holds the org's private key, device.env may hold a password, and with
# -AtSystemStartup SYSTEM runs its scripts. Only this user, SYSTEM and Administrators keep access,
# so another user can neither read the key nor change what runs (SIDs: the same in every language).
$me = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
# The folder gets the three grants; everything in it is reset to inherit them. (Granting with /T
# would leave files with no access at all: the (OI)(CI) flags do not apply to files.)
icacls $here /inheritance:r /grant:r "*S-1-5-18:(OI)(CI)F" "*S-1-5-32-544:(OI)(CI)F" "*${me}:(OI)(CI)F" /C /Q > $null 2>&1
$aclOk = ($LASTEXITCODE -eq 0)
icacls (Join-Path $here "*") /reset /T /C /Q > $null 2>&1
if ($aclOk -and $LASTEXITCODE -eq 0) { Write-Host (T "perms") -ForegroundColor Green } else { Write-Host (T "perms_failed") -ForegroundColor Yellow }

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
