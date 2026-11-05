# setup-certs.ps1 -- copy your EFDI onboarding bundle into .\certs\ (repo root)
#
#   .\demo\setup-certs.ps1 -BundleDir C:\path\to\unpacked-bundle
#
# The bundle holds <prefix>-cert.pem, <prefix>-key.pem, the CA root (efdi-ca-root.pem) and NOTES.md.
# File names are kept: the relay reads the org slot from the certificate itself.
param(
    [Parameter(Mandatory = $true)][string]$BundleDir,
    [string]$CertsOut = (Join-Path (Split-Path -Parent $PSScriptRoot) "certs")
)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not (Test-Path $BundleDir)) { throw "Bundle directory not found: $BundleDir" }

$certs = @(Get-ChildItem $BundleDir -Filter "*-cert.pem" |
    Where-Object { Test-Path (Join-Path $BundleDir ($_.Name -replace '-cert\.pem$', '-key.pem')) })
if ($certs.Count -ne 1) { throw "Expected exactly one <prefix>-cert.pem + -key.pem pair in $BundleDir, found $($certs.Count)" }
$cert = $certs[0].FullName
$key = Join-Path $BundleDir ($certs[0].Name -replace '-cert\.pem$', '-key.pem')

$ca = Join-Path $BundleDir "efdi-ca-root.pem"
if (-not (Test-Path $ca)) {
    $ca = Get-ChildItem $BundleDir -Filter "*.pem" | Where-Object { $_.Name -notmatch "cert|key" } |
        Select-Object -First 1 -ExpandProperty FullName
}
if (-not $ca) { throw "No CA root (efdi-ca-root.pem) in $BundleDir" }

New-Item -ItemType Directory -Force -Path $CertsOut | Out-Null
Copy-Item $cert, $key $CertsOut -Force
Copy-Item $ca (Join-Path $CertsOut "efdi-ca-root.pem") -Force
# NOTES.md names the fabric router ("Router endpoint:"); there is no built-in default.
$notes = Join-Path $BundleDir "NOTES.md"
if (Test-Path $notes) { Copy-Item $notes $CertsOut -Force }
else { Write-Warning "no NOTES.md in ${BundleDir}: set GOAT_ROUTER=tls/<router>:<port>" }
Write-Host "==> certs ready in $CertsOut" -ForegroundColor Green
Get-ChildItem $CertsOut | Select-Object Name, Length | Format-Table -AutoSize
