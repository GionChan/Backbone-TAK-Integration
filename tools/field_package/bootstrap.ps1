# Shared venv + dependency bootstrap. Dot-sourced by run.ps1 and install.ps1 after device.env
# is loaded into the environment. Sets $VenvPython.
$BootstrapDir = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $BootstrapDir "lang.ps1")

# Packages built with the bundled Python (the default) carry python\ with every dependency:
# nothing to install, no network needed.
$bundled = Join-Path $BootstrapDir "python\python.exe"
if (Test-Path $bundled) {
    $VenvPython = $bundled
    return
}

if (-not $Python) { $Python = "python" }

if (-not (Get-Command $Python -ErrorAction SilentlyContinue)) {
    Write-Host (T "no_python" $Python) -ForegroundColor Red
    exit 1
}

$venv = Join-Path $BootstrapDir ".venv"
if (-not (Test-Path (Join-Path $venv "Scripts\python.exe"))) {
    Write-Host (T "venv") -ForegroundColor Cyan
    & $Python -m venv $venv
}
$VenvPython = Join-Path $venv "Scripts\python.exe"

# cryptography reads the TAK Server .p12 files; only installed when they are used.
$packages = @("eclipse-zenoh==1.9.0")
if ($env:TAK_MODE -eq "server" -or $env:TAK_SERVER_P12 -or $env:TAK_SERVER_TRUST_P12) {
    $packages += "cryptography==46.0.3"
}
$marker = Join-Path $venv "deps-installed.txt"
$installed = if (Test-Path $marker) { @(Get-Content $marker) } else { @() }
$missing = @($packages | Where-Object { $installed -notcontains $_ })
if ($missing.Count -gt 0) {
    Write-Host (T "deps" ($missing -join ", ")) -ForegroundColor Cyan
    & $VenvPython -m pip install --quiet --upgrade pip
    & $VenvPython -m pip install --quiet @missing
    if ($LASTEXITCODE -ne 0) { Write-Host (T "pip_failed") -ForegroundColor Red; exit 1 }
    @($installed + $missing) | Out-File -FilePath $marker -Encoding utf8
}
