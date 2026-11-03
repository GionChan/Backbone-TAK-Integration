# CI only (windows-latest, admin runner): installs the field package the way a user does and checks it.
#   1. English + direct, answers typed into the prompts   2. Finnish + local network + device uid
# Each run: build the package (fake bundle), unzip, install.ps1 under Windows PowerShell 5.1 with
# answers on stdin, check device.env, the printed language, the running relay (/status), then
# uninstall and check that the task and the processes are gone.
# The fake certificate means the relay cannot reach the fabric; it still serves /status.
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$root = Join-Path ([IO.Path]::GetTempPath()) "field-install-ci"
Remove-Item -Recurse -Force $root -ErrorAction SilentlyContinue
New-Item -ItemType Directory $root | Out-Null
$failures = @()

function Check([string]$Name, [bool]$Ok, [string]$Detail = "") {
    if ($Ok) { Write-Host "PASS $Name" } else { Write-Host "FAIL $Name $Detail"; $script:failures += $Name }
}

function Get-Status([int]$Port, [int]$WaitSeconds) {
    $end = (Get-Date).AddSeconds($WaitSeconds)
    while ((Get-Date) -lt $end) {
        try { return Invoke-RestMethod -Uri "http://127.0.0.1:$Port/status" -TimeoutSec 3 } catch { Start-Sleep -Seconds 2 }
    }
    return $null
}

function Test-Install([string]$Name, [string]$System, [string[]]$Answers, [hashtable]$ExpectEnv, [string[]]$ExpectText) {
    Write-Host "`n=== $Name"
    $work = Join-Path $root $System
    $certs = Join-Path $work "bundle"
    New-Item -ItemType Directory $certs -Force | Out-Null
    $slot = "0123456789abcdef0123456789abcdef"
    "fake-cert" | Set-Content (Join-Path $certs "$slot-cert.pem")
    "fake-key" | Set-Content (Join-Path $certs "$slot-key.pem")
    "fake-ca" | Set-Content (Join-Path $certs "efdi-ca-root.pem")
    python (Join-Path $repo "tools\make_relay_package.py") --system $System --cert-dir $certs --out (Join-Path $work "pkg.zip") | Out-Null
    $pkg = Join-Path $work "pkg"
    Expand-Archive (Join-Path $work "pkg.zip") $pkg

    $answersFile = Join-Path $work "answers.txt"
    $Answers | Set-Content $answersFile -Encoding ASCII
    $outFile = Join-Path $work "out.txt"
    $errFile = Join-Path $work "err.txt"
    $p = Start-Process powershell.exe -WorkingDirectory $pkg -Wait -PassThru -NoNewWindow `
        -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", (Join-Path $pkg "install.ps1") `
        -RedirectStandardInput $answersFile -RedirectStandardOutput $outFile -RedirectStandardError $errFile
    $out = (Get-Content $outFile -Raw) + (Get-Content $errFile -Raw)
    Write-Host $out
    Check "$Name / installer exit code 0" ($p.ExitCode -eq 0) "code $($p.ExitCode)"

    $envValues = @{}
    Get-Content (Join-Path $pkg "device.env") | ForEach-Object {
        if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$') { $envValues[$Matches[1]] = $Matches[2] }
    }
    foreach ($k in $ExpectEnv.Keys) {
        Check "$Name / device.env $k=$($ExpectEnv[$k])" ($envValues[$k] -eq $ExpectEnv[$k]) "got '$($envValues[$k])'"
    }
    foreach ($t in $ExpectText) { Check "$Name / prints '$t'" ($out -like "*$t*") }

    $status = Get-Status 8088 120
    Check "$Name / relay answers on :8088" ($null -ne $status)
    if ($status) {
        Check "$Name / /status mode" ($status.mode -eq $ExpectEnv["TAK_MODE"]) "got '$($status.mode)'"
        Check "$Name / /status system" ($status.system -eq $System) "got '$($status.system)'"
    }
    $task = "EFDI-TAK-Relay-$System"
    schtasks /Query /TN $task > $null 2>&1
    $hasTask = ($LASTEXITCODE -eq 0)
    $shortcut = Join-Path ([Environment]::GetFolderPath('Startup')) "$task.lnk"
    Check "$Name / automatic start registered" ($hasTask -or (Test-Path $shortcut))

    powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $pkg "uninstall.ps1") | Write-Host
    Start-Sleep -Seconds 3
    schtasks /Query /TN $task > $null 2>&1
    Check "$Name / task removed" ($LASTEXITCODE -ne 0)
    Check "$Name / shortcut removed" (-not (Test-Path $shortcut))
    $left = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
            Where-Object { $_.CommandLine -like "*tak_gateway.py*" -and $_.CommandLine -like "*$pkg*" })
    Check "$Name / relay stopped" ($left.Count -eq 0) "$($left.Count) still running"
    Check "$Name / port 8088 free again" ($null -eq (Get-Status 8088 5))
}

# 1. English, direct. Answers: language 2 = English, mode 1 = direct.
Test-Install "en-direct" "ci-relay-en" @("2", "1") `
    @{ RELAY_LANG = "en"; TAK_MODE = "direct" } `
    @("Choose language", "Installation complete.", "Next, in the TAK app:", "Set the CoT input to UDP port 6969")

# 2. Finnish, local network, one device uid. Answers: 1 = Suomi, 2 = multicast, the uid.
Test-Install "fi-multicast" "ci-relay-fi" @("1", "2", "ANDROID-ci") `
    @{ RELAY_LANG = "fi"; TAK_MODE = "multicast"; TAK_INGEST_UIDS = "ANDROID-ci" } `
    @("Valitse kieli", "Asennus valmis.", "Seuraavaksi TAK-ohjelmaan:")

Write-Host ""
if ($failures.Count -gt 0) { Write-Host "INSTALL TEST FAILED: $($failures -join '; ')"; exit 1 }
Write-Host "INSTALL TEST PASSED"
exit 0
