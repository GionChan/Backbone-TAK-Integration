# Changelog

## 1.0.0 — 2026-11-03

First public release.

### Relay (`relay/`)

- Backbone → TAK: CoT from any vendor plus `goat.geo.track.v1`, MAVLink, Consilium, HYMOTS,
  Orion, ADS-B, protobuf tracks and own JSON telemetry, validated (`cot_guard`), rate-limited and
  de-duplicated.
- Outputs: several UDP targets (`TAK_UDP_TARGETS`), a TCP server for ATAK/WinTAK and TCP/TLS
  clients towards a TAK Server. Each TCP client has its own queue and writer thread, so a client
  that stops reading cannot stall the others.
- TAK → backbone: optional friendly PLI to `<slot>/tak/pli/v1/<uid>` (`TAK_INGEST=1`).
- Operations: mandatory heartbeat from a real health check, `/healthz`, `/metrics`, `/status`,
  `/streams`, watchdog restart.
- Optional video restream (MediaMTX + ffmpeg → RTSP, CoT `<video>` marker).
- Identity from the certificate bundle: org slot from `GOAT_ORG` or the certificate CN; the
  relay refuses to start with a certificate but no slot.
- Docker image (targets `relay` and `demo`, UID 10001, amd64 and arm64) and a self-installing
  Windows field package (`tools/make_relay_package.py`).

### Demo (`demo/`)

- Scenarios (drone swarm, strike package, mass-raid CSV) publish only through
  `demo/sender.py`, exercise-labelled, to `<slot>/exercise/**` and `<slot>/tak/cot/v1/EXERCISE.*`.
- Live map with control panel, local router for offline use, Windows launcher, edge-AI demo.

### Upgrading from a pre-release checkout

- `app/` is now `relay/`; scenarios, map, launcher and monitor are under `demo/`.
- Certificates are found in `certs/` or `GOAT_CERT_DIR`; file names no longer matter.
- `run-backbone-demo.ps1` is `demo/run-backbone-demo.ps1`; `-NoDrones` is now `-NoSwarm`.
- Compose service `drone-swarm` is now `swarm-orbit` (profile `demo`).
- `docker compose up -d` starts the relay only; the demo needs `--profile demo`.
