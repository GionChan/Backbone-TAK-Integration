# CI only (windows-latest, admin runner): installs the field package the way a user does and checks it.
#   1. English + direct, bundled Python, with every Python hidden from PATH (proves no Python needed)
#   2. Finnish + local network + device uid, package without bundled Python (venv + pip path)
#   3. Template package (no certificate, no name): bundle given as a .zip, device name typed in.
#      -TemplateZip <zip> runs only this case, on that exact zip (the release artifact).
# Each run: build the package (fake bundle), unzip, install.ps1 under Windows PowerShell 5.1 with
# answers on stdin, check device.env, the printed language, the running relay (/status), then
# uninstall and check that the task and the processes are gone.
# The fake certificate means the relay cannot reach the fabric; it still serves /status.
param([string]$TemplateZip = "")
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

function Test-Install([string]$Name, [string]$System, [string[]]$Answers, [hashtable]$ExpectEnv, [string[]]$ExpectText,
                      [string[]]$BuildArgs = @(), [switch]$HidePython, [string]$Zip = "", [switch]$Template) {
    Write-Host "`n=== $Name"
    $work = Join-Path $root $System
    $certs = Join-Path $work "bundle\efdi-onboarding-ci"
    New-Item -ItemType Directory $certs -Force | Out-Null
    $slot = "0123456789abcdef0123456789abcdef"
    "fake-cert" | Set-Content (Join-Path $certs "$slot-cert.pem")
    "fake-key" | Set-Content (Join-Path $certs "$slot-key.pem")
    "fake-ca" | Set-Content (Join-Path $certs "efdi-ca-root.pem")
    "Router endpoint:     tls/router.invalid:7447" | Set-Content (Join-Path $certs "NOTES.md")
    $bundleZip = Join-Path $work "efdi-onboarding-ci.zip"
    Compress-Archive -Path (Join-Path $work "bundle\*") -DestinationPath $bundleZip
    if (-not $Zip) {
        $Zip = Join-Path $work "pkg.zip"
        # [string[]]: a one-element array would otherwise become a string, and @target would splat its letters.
        [string[]]$target = if ($Template) { @("--template") } else { @("--system", $System, "--cert-dir", $certs) }
        python (Join-Path $repo "tools\make_relay_package.py") @target --out $Zip @BuildArgs | Out-Null
    }
    $pkg = Join-Path $work "pkg"
    Expand-Archive $Zip $pkg
    if ($Template) {
        Check "$Name / template has no certificate" (@(Get-ChildItem (Join-Path $pkg "certs") -Recurse -Include *.pem, *.key, *.p12).Count -eq 0)
        $Answers = $Answers | ForEach-Object { $_ -replace '<BUNDLE>', $bundleZip }
    }
    $bundledPython = Join-Path $pkg "python\python.exe"
    Check "$Name / bundled Python present = $(-not ($BuildArgs -contains '--no-bundled-python'))" `
        ((Test-Path $bundledPython) -eq (-not ($BuildArgs -contains '--no-bundled-python')))

    $savedPath = $env:PATH
    if ($HidePython) {
        $env:PATH = (($env:PATH -split ';') | Where-Object { $_ -and $_ -notmatch 'python|WindowsApps' }) -join ';'
        Check "$Name / no python on PATH for the installer" ($null -eq (Get-Command python -ErrorAction SilentlyContinue))
    }

    $answersFile = Join-Path $work "answers.txt"
    $Answers | Set-Content $answersFile -Encoding ASCII
    $outFile = Join-Path $work "out.txt"
    $errFile = Join-Path $work "err.txt"
    $p = Start-Process powershell.exe -WorkingDirectory $pkg -Wait -PassThru -NoNewWindow `
        -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", (Join-Path $pkg "install.ps1") `
        -RedirectStandardInput $answersFile -RedirectStandardOutput $outFile -RedirectStandardError $errFile
    $env:PATH = $savedPath
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
    if ($Template) {
        Check "$Name / certificate copied from the zip" (Test-Path (Join-Path $pkg "certs\$slot-cert.pem"))
        Check "$Name / key copied" (Test-Path (Join-Path $pkg "certs\$slot-key.pem"))
        Check "$Name / NOTES.md copied (router)" (Test-Path (Join-Path $pkg "certs\NOTES.md"))
        Check "$Name / unpacked bundle removed from temp" `
            (@(Get-ChildItem ([IO.Path]::GetTempPath()) -Filter "efdi-bundle-*" -ErrorAction SilentlyContinue).Count -eq 0)
    }

    # Folder limited to the installing user, SYSTEM and Administrators; the key readable by the user.
    $open = @((Get-Acl $pkg).Access + (Get-Acl (Get-ChildItem (Join-Path $pkg "certs") -Filter "*.pem" | Select-Object -First 1).FullName).Access |
        Where-Object { $_.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value -in @("S-1-1-0", "S-1-5-11", "S-1-5-32-545") })
    Check "$Name / no access for Everyone, Authenticated Users or Users" ($open.Count -eq 0) "$($open.IdentityReference -join ', ')"
    Check "$Name / prints the permissions line" ($out -like "*Folder limited*" -or $out -like "*Kansio rajattu*")
    $status = Get-Status 8088 120
    Check "$Name / relay answers on :8088" ($null -ne $status)
    if ($status) {
        Check "$Name / /status mode" ($status.mode -eq $ExpectEnv["TAK_MODE"]) "got '$($status.mode)'"
        Check "$Name / /status system" ($status.system -eq $System) "got '$($status.system)'"
    }
    $running = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
            Where-Object { $_.CommandLine -like "*tak_gateway.py*" -and $_.CommandLine -like "*$pkg*" })
    if (Test-Path $bundledPython) {
        Check "$Name / relay runs on the bundled Python" (@($running | Where-Object { $_.ExecutablePath -eq $bundledPython }).Count -ge 1) `
            "$($running.ExecutablePath -join ', ')"
        Check "$Name / no venv created" (-not (Test-Path (Join-Path $pkg ".venv")))
    } else {
        Check "$Name / venv created" (Test-Path (Join-Path $pkg ".venv\Scripts\python.exe"))
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

# 3. Template: no certificate, no name. Answers: 2 = English, bundle zip, device name, 1 = direct,
#    1 = do not share markers.
$templateCase = @{
    Name = "en-template"; System = "ci-relay-tpl"; Answers = @("2", "<BUNDLE>", "ci-relay-tpl", "1", "1")
    ExpectEnv = @{ RELAY_LANG = "en"; TAK_MODE = "direct"; GATEWAY_SYSTEM = "ci-relay-tpl"; TAK_SHARE_MARKERS = "0" }
    ExpectText = @("No EFDI certificate bundle found", "Certificate copied", "Installation complete.")
}
if ($TemplateZip) {
    Test-Install @templateCase -Zip (Resolve-Path $TemplateZip).Path -Template -HidePython
    if ($failures.Count -gt 0) { Write-Host "`nINSTALL TEST FAILED: $($failures -join '; ')"; exit 1 }
    Write-Host "`nINSTALL TEST PASSED"
    exit 0
}

# 1. English, direct, bundled Python, no Python on PATH. Answers: 2 = English, 1 = direct, 1 = no sharing.
Test-Install "en-direct" "ci-relay-en" @("2", "1", "1") `
    @{ RELAY_LANG = "en"; TAK_MODE = "direct"; TAK_SHARE_MARKERS = "0" } `
    @("Choose language", "Installation complete.", "Next, in the TAK app:", "Set the CoT input to UDP port 6969") `
    -HidePython

# 2. Finnish, local network, one device uid, no bundled Python. Answers: 1 = Suomi, 2 = multicast,
#    2 = share markers, the uid.
Test-Install "fi-multicast" "ci-relay-fi" @("1", "2", "2", "ANDROID-ci") `
    @{ RELAY_LANG = "fi"; TAK_MODE = "multicast"; TAK_INGEST_UIDS = "ANDROID-ci"; TAK_SHARE_MARKERS = "1" } `
    @("Valitse kieli", "Asennus valmis.", "Seuraavaksi TAK-ohjelmaan:", "Merkkien ja piirrosten jako: päällä") `
    -BuildArgs @("--no-bundled-python")

Test-Install @templateCase -Template -BuildArgs @("--no-bundled-python")

Write-Host ""
if ($failures.Count -gt 0) { Write-Host "INSTALL TEST FAILED: $($failures -join '; ')"; exit 1 }
Write-Host "INSTALL TEST PASSED"
exit 0
