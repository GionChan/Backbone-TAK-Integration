# Changelog

## 1.2.0 — 2026-11-05

### Relay

- `TAK_SHARE_MARKERS=1` shares markers and drawings made on TAK devices to
  `<slot>/tak/cot/v1/<uid>`: every CoT event with a `<link relation="p-p">` to the device that made
  it, hostile markers too. A deletion (`t-x-d-d`) follows for markers this relay published. Off by
  default; independent of `TAK_INGEST` (PLI). The installers ask for it; `/status`, the status page
  and `doctor.py` show it.
- Messages (GeoChat and every other `b-t-*`) are never published, whatever the settings.
- `TAK_INGEST_UIDS=*` lets any device on the allowed links publish.
- A user-placed friendly marker (`a-f-*` with a creator link) is no longer published as the
  device's PLI; it is a marker and follows `TAK_SHARE_MARKERS`.
- New drop reasons `chat`, `markers-off`, `pli-off`, `delete-unknown`; counters
  `gateway_markers_published_total` and `gateway_marker_deletes_published_total`.

### Field package

- Linux package: `make_relay_package.py --platform linux` builds a `.tar.gz` with `install.sh`,
  `run.sh` and `uninstall.sh`, messages in Finnish and English, and the dependency wheels for
  x86_64 and aarch64, so installing needs no network. The relay starts as a systemd user service,
  with `--at-boot` as a systemd service that runs as the installing user, or from crontab without
  systemd. The package folder and `certs/` are 700, the key and `device.env` 600.
- In direct mode the Linux installer also asks where CoT goes by UDP and which other devices may
  publish their position.
- Releases carry a Linux template, `efdi-tak-relay-X.Y.Z-linux.tar.gz`, installed on Ubuntu before
  publishing.

### Demo

- `demo/run-backbone-demo.sh` and `demo/setup-certs.sh` for Linux and macOS.

### Deployment

- Compose maps `host.docker.internal` to the Docker host, so the default UDP target works with
  Docker Engine on Linux too.

## 1.1.4 — 2026-11-05

### Relay

- No built-in fabric router: the router comes from `GOAT_ROUTER` or the "Router endpoint" line of
  the bundle's `NOTES.md`. With a certificate but neither, the relay stops at start with the fix,
  and `doctor.py` reports it. Copy `NOTES.md` together with the certificate.

### Deployment

- Compose: the Docker Desktop host mapping takes the router name and mesh IP from
  `EFDI_ROUTER_HOST` and `EFDI_ROUTER_IP`; there is no default address.
- `make_relay_package.py` stops when neither `--router` nor the bundle's `NOTES.md` names a router.
- `demo/setup-certs.ps1` copies `NOTES.md`; the demo launcher reads the router from it.

### Demo

- The live map has no button for an external portal.

## 1.1.3 — 2026-11-05

### Relay

- `adsb`, `alerts` and `roi` reach TAK again: they had no rate limiter and every message failed.
- `/metrics` writes one `# TYPE` line per metric; before, Prometheus rejected the scrape as soon
  as a metric had two labelled series.
- CoT must be UTF-8 (or another ASCII-compatible encoding) with exactly one `<event>`. New drop
  reasons `not-utf8` and `not-one-event`. A UDP or multicast datagram that holds more than one
  event is dropped (`reason="multi-event-datagram"`).
- TAK Server TLS: a truststore (`TAK_SERVER_TRUST_P12` or `TAK_SERVER_CA`) replaces the operating
  system's public CAs instead of being added to them.
- TAK Server link: one thread reads and writes the connection; sending and receiving give up
  after 10 s without progress, and a link the server closed is noticed and reconnected.
- `TAK_MAX_CLIENTS_PER_IP` (default 8) limits TCP clients per address.
- A wrong number in `TAK_MAX_CLIENTS` or `TAK_MAX_CLIENTS_PER_IP` stops the relay with a
  configuration error.
- A warning at start and in `doctor.py` when `TAK_INGEST=1` runs in Docker without
  `TAK_INGEST_UIDS`, and one log line per address whose PLI is dropped as `not-loopback`.

### Demo

- Live map: `/inject` accepts only `application/json` and sends no `Access-Control-Allow-Origin`;
  numeric fields are checked, and values from the backbone are cleaned before the map shows them.
- Edge-AI API: published on the host's `127.0.0.1` only; the token is compared in constant time.
- The demo launcher sets `GATEWAY_VIDEO_HOST=127.0.0.1` when it is not set.

### Deployment

- Docker image: `GATEWAY_HTTP_BIND=127.0.0.1` by default; compose sets `0.0.0.0` in the container
  and still publishes 8088 on the host's `127.0.0.1` only.
- Compose: no default for `GATEWAY_VIDEO_HOST`; without it the video restream stays off instead of
  sending TAK clients an address they cannot reach.
- Release workflow: the image is built once into an OCI archive, each architecture is tested from
  that archive, and the same archive is pushed.

## 1.1.2 — 2026-11-04

### Relay

- PLI ingest without `TAK_INGEST_UIDS` publishes only events from this machine (loopback).
  Devices on other machines need their uid in `TAK_INGEST_UIDS`; in Docker this includes TAK
  apps on the host. New drop reason `not-loopback`.
- CoT with `<!DOCTYPE` or `<!ENTITY` anywhere is rejected (before, only the first 4 KiB were
  checked).
- Generated CoT escapes `type` and `how`. A CoT type given by a source must consist of letters,
  digits, `_` and `-`; `gateway_cot_type_total` counts only such types.
- `TAK_MAX_CLIENTS` (default 64) caps TCP clients on `TAK_PORT`; further connections are refused
  (`gateway_output_rejected_total`).
- `GATEWAY_HTTP_BIND` (default `127.0.0.1`): the HTTP port listens on this machine only. The
  Docker image sets `0.0.0.0`, and compose publishes 8088 on the host's `127.0.0.1` only.

### Demo

- Edge-AI CoT escapes every attribute value.

### Deployment

- Release workflow pushes the image only after the image, field-package and Windows install
  checks have passed.
- mediamtx in the Docker image is checked against a pinned SHA256.
- `tests/test_stream_view.py` skips the image tests when Pillow is not installed.
- Generic TAK client names in code comments, the `device.env` template and the demo launcher.

## 1.1.1 — 2026-11-04

### Deployment

- Release workflow: the publish job downloads only the field package and the release notes, and
  the image build uploads no build record. Downloading that record failed when 1.1.0 was
  published.

### Documentation

- Recognised backbone formats are listed in one table in docs/*/relay.md ("Recognised formats").
  Other docs name TAK clients generically.

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
