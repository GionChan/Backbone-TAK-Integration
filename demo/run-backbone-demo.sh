#!/usr/bin/env bash
# run-backbone-demo.sh -- EFDI backbone + TAK demo, one-command launcher (Linux, macOS).
# The same as run-backbone-demo.ps1:
#   - certs in ./certs (copied from --bundle-dir on first run)
#   - the TAK relay (product) -> CoT by UDP to the host's 6969, TCP :8087
#   - demo profile: local router, live map :8080, swarm-orbit scenario
#   - native strike-package scenario, published through the real fabric from this peer
# Every demo track is exercise-labelled (demo/sender.py) and reaches TAK through the relay.
#
#   demo/run-backbone-demo.sh --bundle-dir /path/to/bundle   first run (copies certs)
#   demo/run-backbone-demo.sh              start everything
#   demo/run-backbone-demo.sh --no-swarm   without the swarm-orbit container
#   demo/run-backbone-demo.sh --edge-ai    + edge-AI node + synthetic EO feed
#   demo/run-backbone-demo.sh --edge-api   + HTTP <-> backbone gateway on :8090
#   demo/run-backbone-demo.sh --stop       tear everything down
#
# Prereqs: NetBird connected, Docker with the compose plugin, python3 with eclipse-zenoh==1.9.0.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
cd "$root"
logs=$root/logs
mkdir -p "$logs"

stop=0 no_swarm=0 edge_ai=0 edge_api=0 bundle_dir=""
while [ $# -gt 0 ]; do
    case $1 in
        --stop) stop=1 ;;
        --no-swarm) no_swarm=1 ;;
        --edge-ai) edge_ai=1 ;;
        --edge-api) edge_api=1 ;;
        --bundle-dir) bundle_dir=${2:?--bundle-dir needs a folder}; shift ;;
        *) echo "usage: $0 [--bundle-dir DIR] [--no-swarm] [--edge-ai] [--edge-api] [--stop]" >&2; exit 2 ;;
    esac
    shift
done

if [ "$stop" = 1 ]; then
    echo "==> stopping native scenarios + docker stack"
    if [ -f "$logs/strike.pid" ]; then
        kill "$(cat "$logs/strike.pid")" 2> /dev/null || true
        rm -f "$logs/strike.pid"
    fi
    docker compose --profile demo --profile edge --profile edge-api down
    exit 0
fi

# 1. certs
if ! compgen -G "$root/certs/*-cert.pem" > /dev/null; then
    [ -n "$bundle_dir" ] || { echo "no certs in ./certs -- pass --bundle-dir <unpacked onboarding bundle>" >&2; exit 1; }
    "$root/demo/setup-certs.sh" "$bundle_dir"
fi

# 2. backbone router (GOAT_ROUTER, else the bundle's NOTES.md) reachable over the mesh?
endpoint=$(python3 -c "import sys; sys.path.insert(0, 'relay'); import identity; print(identity.router_for(identity.resolve_bundle()[0]))")
if [[ ! $endpoint =~ ^tls/(.+):([0-9]+)$ ]]; then
    echo "no fabric router: set GOAT_ROUTER=tls/<router>:<port> or put the bundle's NOTES.md in ./certs" >&2
    exit 1
fi
router_host=${BASH_REMATCH[1]} router_port=${BASH_REMATCH[2]}
ip=$(python3 -c "import socket, sys; print(socket.gethostbyname(sys.argv[1]))" "$router_host" 2> /dev/null) ||
    { echo "cannot resolve $router_host - is NetBird up? (netbird status)" >&2; exit 1; }
python3 -c "import socket, sys; socket.create_connection((sys.argv[1], int(sys.argv[2])), timeout=5).close()" "$ip" "$router_port" 2> /dev/null ||
    { echo "backbone router $ip:$router_port unreachable - check 'netbird status' (Management: Connected, Nameservers 1/1)" >&2; exit 1; }
echo "==> backbone router reachable at $ip:$router_port"

# 3. relay + demo stack (demo settings; the product defaults live in docker-compose.yml)
export EFDI_ROUTER_HOST=$router_host EFDI_ROUTER_IP=$ip
export TAK_UDP_TARGETS=${TAK_UDP_TARGETS:-host.docker.internal:6969}
export TAK_INGEST=1 GATEWAY_VIDEO=1
# RTSP address in the video markers: TAK apps on this machine. For phones, set your LAN IP first.
export GATEWAY_VIDEO_HOST=${GATEWAY_VIDEO_HOST:-127.0.0.1}
svc=()
[ "$no_swarm" = 0 ] || svc=(tak-relay zenoh-router live-map)
docker compose --profile demo up -d --build ${svc[@]+"${svc[@]}"}
echo "==> relay + demo stack up  (map http://localhost:8080, relay status http://localhost:8088/status)"

# 4. native scenario: 10 strike-package tracks from THIS peer, through the fabric
nohup python3 -u demo/scenarios/strike_package.py > "$logs/strike.out.log" 2> "$logs/strike.err.log" &
echo $! > "$logs/strike.pid"
echo "==> strike_package.py started  (logs/strike.*.log)"

# 5. edge-AI demo (opt-in)
if [ "$edge_ai" = 1 ]; then
    docker compose --profile edge up -d --build edge-ai frame-pub
    echo "==> edge-ai + frame-pub up  (their CoT reaches TAK through the relay)"
fi
if [ "$edge_api" = 1 ]; then
    docker compose --profile edge-api up -d --build edge-api
    echo "==> edge-api up  (http://localhost:8090  GET /intake/frames  POST /detections/cot)"
fi

echo
echo "TAK apps on this machine: CoT on UDP 6969. ATAK and WinTAK on other devices: TCP <this-ip>:8087."
echo "PLI from TAK apps needs TAK_INGEST_UIDS (the relay runs in Docker)."
echo "Monitor: python3 demo/tools/live_monitor.py      Stop: demo/run-backbone-demo.sh --stop"
