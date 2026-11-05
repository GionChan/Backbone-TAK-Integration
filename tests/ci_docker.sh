#!/usr/bin/env bash
# CI only (ubuntu-latest): builds the images, starts the relay against the demo's local router and
# waits for Docker's own HEALTHCHECK to report "healthy". Then checks doctor inside the container
# and that the multicast override is valid. Leaves nothing running.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p certs                     # empty: the relay uses the local router
trap 'docker compose --profile demo logs --no-color tak-relay | tail -40; docker compose --profile demo down -v' EXIT

docker compose --profile demo build tak-relay zenoh-router
docker compose --profile demo up -d zenoh-router tak-relay

cid=$(docker compose ps -q tak-relay)
for _ in $(seq 1 60); do
  state=$(docker inspect -f '{{.State.Health.Status}}' "$cid")
  echo "health: $state"
  [ "$state" = "healthy" ] && break
  [ "$state" = "unhealthy" ] && { echo "FAIL: container unhealthy"; exit 1; }
  sleep 5
done
[ "$state" = "healthy" ] || { echo "FAIL: not healthy in time"; exit 1; }

curl -fsS localhost:8088/status | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['healthy'], d; assert d['mode']=='direct', d; print('status ok', d['version'], d['mode'])"
curl -fsS localhost:8088/ | grep -q "TAK relay" && echo "status page ok"
docker compose exec -T tak-relay python3 relay/doctor.py || { echo "FAIL: doctor reported a failure"; exit 1; }
docker compose exec -T tak-relay python3 -c "import cryptography; print('cryptography', cryptography.__version__)"
docker compose -f docker-compose.yml -f docker-compose.multicast.yml config -q && echo "multicast override ok"
echo "DOCKER TEST PASSED"
