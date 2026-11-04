# Changelog

## 1.1.1 — 2026-11-04

### Demo

- Scenarios renamed: `swarm_orbit.py` (compose service `swarm-orbit`), `strike_package.py`,
  `mass_raid.csv`. The live map's scripted scenario names its targets A–E.

### Documentation

- References to events, dates and places removed.

## 1.1.0 — 2026-11-04

### Relay

- PLI ingest publishes only your own devices. Events from a TAK Server link (other users) are
  never published unless `TAK_INGEST_FROM=local,server`.
- `TAK_INGEST_UIDS`: allowlist of device uids that may publish.
- Echo guard: a uid the relay sent to TAK in the last 60 s is not published back.
- New drop reasons `not-local`, `not-allowed`, `echo` in `gateway_ingest_dropped_total`.
- TAK Server link from env: `TAK_SERVER`, client certificate and truststore as .p12
  (`TAK_SERVER_P12`, `TAK_SERVER_TRUST_P12`) or PEM. The decrypted key never stays on disk.
- Router endpoint read from the bundle's `NOTES.md` when `GOAT_ROUTER` is not set.
- An unpacked `~/Downloads/efdi-onboarding-*` bundle is found automatically (only if there is one).
- `relay/doctor.py`: preflight that checks bundle, slot, certificate expiry, NetBird, router,
  ports and TAK Server, with a fix for each failure. The field package's `run.ps1 -CheckOnly`
  runs it.
- Status page for people at `/`; `/status` adds `version`, `org`, `system`, ingest settings.

### Modes (`TAK_MODE`)

- One setting picks how TAK devices get the picture: `direct` (default, as before), `multicast`
  (TAK SA group 239.2.3.1:6969, nothing to set in TAK, closed networks only) or `server`
  (TAK Server; local outputs off unless `TAK_LOCAL_OUTPUTS=1`). See docs/en/modes.md.
- An impossible set-up (e.g. `server` without `TAK_SERVER`) stops the relay at start with the fix.
- Multicast: positions heard on the LAN (`lan`) are published only for `TAK_INGEST_UIDS`.
- Every CoT the relay sends carries `<__efdi_relay/>`; tagged events are never published
  (`reason="relayed"`), so relays cannot loop markers back to the backbone.
- `doctor.py`, `/status` and the status page show and check the mode.
- `docker-compose.multicast.yml` for multicast on a Linux host network.

### Field package

- Installer asks first for the language (Suomi / English), then the mode and its details; all
  later messages (install, start, uninstall) are in that language. Choices go to `device.env`.
- `make_relay_package.py --lang --mode --tak-server --tak-p12 --tak-trust-p12 --ingest-uids`
  preset the answers. The TAK Server password is only asked at install.
- Scripts moved to `tools/field_package/` and written with a UTF-8 BOM (Finnish letters in
  Windows PowerShell 5.1). READMEs in both languages.
- Python is included by default: embeddable Python 3.14.10 (pinned SHA256) and the Windows
  wheels, so the device needs no Python and no network at install (`--no-bundled-python` for
  the old venv + pip way, where `cryptography` is installed only in TAK Server mode).

### Deployment

- Release workflow: a tag `vX.Y.Z` publishes the image (amd64 + arm64, SBOM, provenance) to GHCR
  and a GitHub Release with the field-package template and SHA256SUMS, after checking versions,
  both architectures, that the template holds no secret, and installing that exact ZIP on
  Windows. `feature/**` pushes are a dry run. See docs/en/release.md.
- `make_relay_package.py --template`: no certificate and no device name; the installer asks for
  the bundle (folder, .zip, .tar.gz, suggested from Downloads) and the name.
- Installer prompts give up after 10 invalid answers instead of looping forever.

- Docker image has a `HEALTHCHECK` on `/healthz` (also for plain `docker run`).
- `cryptography` added to `relay/requirements.txt` (only needed for .p12).
- Compose: `GOAT_ROUTER` empty by default (bundle notes win), TAK Server variables, image tag 1.1.0.

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
