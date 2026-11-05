# run-backbone-demo.ps1 -- EFDI backbone + TAK demo, one-command launcher (Windows)
#
# Brings up, on this Windows NetBird peer:
#   - certs in .\certs\ (copied from -BundleDir on first run)
#   - the TAK relay (product) -> CoT by UDP to 6969 and to WinTAK (UDP 4242), TCP :8087
#   - demo profile: local router, live map :8080, swarm-orbit scenario
#   - native strike-package scenario, published through the real fabric from this peer
# Every demo track is exercise-labelled (demo/sender.py) and reaches TAK through the relay.
#
#   .\demo\run-backbone-demo.ps1 -BundleDir C:\path\to\bundle   first run (copies certs)
#   .\demo\run-backbone-demo.ps1             start everything
#   .\demo\run-backbone-demo.ps1 -NoSwarm    without the swarm-orbit container
#   .\demo\run-backbone-demo.ps1 -EdgeAI     + edge-AI node + synthetic EO feed
#   .\demo\run-backbone-demo.ps1 -EdgeApi    + HTTP <-> backbone gateway on :8090
#   .\demo\run-backbone-demo.ps1 -Stop       tear everything down
#
# Prereqs: NetBird connected, Docker Desktop running, Python 3.10+ with eclipse-zenoh==1.9.0.

param(
    [switch]$Stop,
    [switch]$NoSwarm,
    [switch]$EdgeAI,
    [switch]$EdgeApi,
    [string]$BundleDir
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$logs = Join-Path $root "logs"
New-Item -ItemType Directory -Force -Path $logs | Out-Null

if ($Stop) {
    Write-Host "==> stopping native scenarios + docker stack" -ForegroundColor Cyan
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -match "strike_package" } |
        ForEach-Object { Write-Host "   kill pid $($_.ProcessId)"; Stop-Process -Id $_.ProcessId -Force }
    docker compose --profile demo --profile edge --profile edge-api down
    return
}

# 1. certs
$haveCert = @(Get-ChildItem (Join-Path $root "certs") -Filter "*-cert.pem" -ErrorAction SilentlyContinue).Count -gt 0
if (-not $haveCert) {
    if (-not $BundleDir) { throw "no certs in .\certs\ -- pass -BundleDir <unpacked onboarding bundle>" }
    & (Join-Path $PSScriptRoot "setup-certs.ps1") -BundleDir $BundleDir
}

# 2. backbone router reachable over the mesh?
try {
    $ip = [System.Net.Dns]::GetHostAddresses("router.example")[0].IPAddressToString
} catch {
    throw "cannot resolve router.example - is NetBird up? (netbird status)"
}
if (-not (Test-NetConnection -ComputerName $ip -Port 7447 -WarningAction SilentlyContinue).TcpTestSucceeded) {
    throw "backbone router ${ip}:7447 unreachable - check 'netbird status' (Management: Connected, Nameservers 1/1)"
}
Write-Host "==> backbone router reachable at ${ip}:7447" -ForegroundColor Green

# 3. relay + demo stack (demo settings; the product defaults live in docker-compose.yml)
$env:EFDI_ROUTER_IP = $ip
$env:TAK_UDP_TARGETS = "host.docker.internal:6969,host.docker.internal:4242"
$env:TAK_INGEST = "1"
$env:GATEWAY_VIDEO = "1"
# RTSP address in the video markers: TAK apps on this machine. For phones, set your LAN IP first.
if (-not $env:GATEWAY_VIDEO_HOST) { $env:GATEWAY_VIDEO_HOST = "127.0.0.1" }
$svc = if ($NoSwarm) { @("tak-relay", "zenoh-router", "live-map") } else { @() }
docker compose --profile demo up -d --build @svc
Write-Host "==> relay + demo stack up  (map http://localhost:8080, relay status http://localhost:8088/status)" -ForegroundColor Green

# 4. native scenario: 10 strike-package tracks from THIS peer, through the fabric
Start-Process python -ArgumentList "-u", "demo\scenarios\strike_package.py" -WorkingDirectory $root `
    -RedirectStandardOutput "$logs\strike.out.log" -RedirectStandardError "$logs\strike.err.log"
Write-Host "==> strike_package.py started  (logs\strike.*.log)" -ForegroundColor Green

# 5. edge-AI demo (opt-in)
if ($EdgeAI) {
    docker compose --profile edge up -d --build edge-ai frame-pub
    Write-Host "==> edge-ai + frame-pub up  (their CoT reaches TAK through the relay)" -ForegroundColor Green
}
if ($EdgeApi) {
    docker compose --profile edge-api up -d --build edge-api
    Write-Host "==> edge-api up  (http://localhost:8090  GET /intake/frames  POST /detections/cot)" -ForegroundColor Green
}

Write-Host ""
Write-Host "WinTAK: CoT arrives on its Default UDP input (4242). Other TAK apps: UDP 6969. ATAK: TCP <this-ip>:8087." -ForegroundColor Yellow
Write-Host "Monitor: python demo\tools\live_monitor.py      Stop: .\demo\run-backbone-demo.ps1 -Stop" -ForegroundColor Yellow
