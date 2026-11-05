# AGENTS.md — EFDI TAK relay

Machine-oriented guide for AI coding agents. Human docs: README.md (en), README.fi.md (fi),
docs/en/, docs/fi/. When this file and the code disagree, the code wins; fix this file.

## Purpose

Two-way bridge: EFDI goat fabric (Zenoh 1.9.0, mTLS, NetBird mesh) <-> TAK clients (CoT 2.0 XML).
Product = `relay/`. Everything in `demo/` is demonstration only.

## Map

```text
relay/                  PRODUCT. Must not import from demo/ or tools/.
  tak_gateway.py        entry point; subscriptions, outputs, PLI ingest, HTTP ops, watchdog
  goat_connect.py       make_config() -> (zenoh.Config, is_real); ORG, KEY_PREFIX, ROUTER, LOCAL_ROUTER
  identity.py           bundle, org slot, router (NOTES.md) discovery; stdlib only
  tak_links.py          TAK_MODE -> outputs(); UDP targets, multicast, TAK_SERVER*, ssl_context() incl. .p12; stdlib only
  doctor.py             preflight CLI (no zenoh needed); never writes to the fabric
  status_page.py        HTML served at GET /
  backbone_cot.py       vendor format detection -> CoT; make_cot()
  cot_guard.py          validate_cot(), RateLimiter (thread-safe)
  symbology.py heartbeat.py stream_view.py video_relay.py gateway_core.py make_atak_package.py
  requirements.txt      eclipse-zenoh==1.9.0 (required); av, pillow (optional previews)
demo/
  sender.py             ONLY path for demo data into the backbone; adds exercise labels
  scenarios/            compute positions, call sender.Sender.track(); never publish directly
  live_map.py           map :8080, /control injects via sender
  local_router.py       offline Zenoh router :7447
  tools/                live_monitor.py read_cot.py verify_efdi.py
  edge_ai/              edge-AI demo (own Dockerfile; copies relay/heartbeat.py + identity.py)
  run-backbone-demo.ps1/.sh setup-certs.ps1/.sh   (Windows / Linux, macOS)
tools/                  make_relay_package.py (field ZIP, or .tar.gz with --platform linux; --template = publishable, no cert),
                        check_release.py (versions agree), register_portal_topics.py (WRITES PORTAL)
  field_package/        installer scripts + READMEs for the ZIP; lang.ps1 holds every message (fi, en)
                        bundled Python: make_relay_package.EMBED_PYTHON (pinned SHA256) + FIELD_REQUIREMENTS
    linux/              install.sh run.sh uninstall.sh common.sh (systemd; crontab fallback); lang.txt = messages;
                        wheels for LINUX_ARCHES x LINUX_PYTHONS; never run as root (the --at-boot unit has User=)
tests/                  unittest; e2e_gateway.py needs a local router
docker-compose.yml      default = relay only; profiles: demo, edge, edge-api
Dockerfile              targets: relay, demo; layout /opt/tak/{relay,demo}; runs as UID 10001
```

## Commands

```bash
pip install -r relay/requirements.txt
python -m unittest discover -s tests                     # must pass before any commit
python -m compileall -q relay demo tools tests
python relay/doctor.py                                   # preflight; exit 1 on failures
python demo/local_router.py &                            # or: docker compose --profile demo up -d zenoh-router
python tests/e2e_gateway.py                              # prints "GATEWAY E2E PASSED"
shellcheck tools/field_package/linux/*.sh demo/*.sh tests/*.sh   # CI lints every .sh
docker compose up -d                                     # relay only
docker compose --profile demo up -d                      # + demo
```

CI: .github/workflows/tests.yml, windows-latest + ubuntu-latest, Python 3.12.

## Invariants (do not break)

1. Demo data is published only via `demo/sender.py` to `<org>/exercise/<scenario>/v1/<uid>` and
   `<org>/tak/cot/v1/EXERCISE.<uid>`, labelled `exercise: true`, `classification: SIMULATED`.
   Never to `<org>/sensor/v1/**` (real telemetry).
2. All TLS keys go into ONE `insert_json5("transport/link/tls", …)` call. Set separately, the
   client cert can silently go unsent.
3. Writes outside `<org>/**` are silently dropped by the fabric. goat_connect raises SystemExit
   when a cert exists but the org cannot be resolved; keep that.
4. Zenoh callbacks run on several threads. Shared state needs a lock (see `_seen_lock`,
   `RateLimiter._lock`). Callbacks must not block: TCP clients use per-client queues + writer
   threads (`_TcpClient`); never call blocking `sendall` from a callback.
5. Every CoT from other vendors passes `cot_guard.validate_cot()` before `dispatch()`.
   Free-text fields in generated CoT are XML-escaped (`quoteattr`/`escape`).
6. `tools/make_relay_package.APP_FILES` must list every relay module the gateway imports,
   transitively (test: `test_app_files_cover_every_sibling_import`).
7. Heartbeat `<org>/<system>/heartbeat/v1`, interval <= 900 s, `status` from a real health check.
8. Never commit `certs/`, `*.pem`, `*.key`, `*.cbor`, `dist/`, `.env`. Field ZIPs contain the key.
9. Do not hardcode an org slot, a person's name or a home-directory path; use identity.py.
10. PLI ingest publishes only local devices: `_reader(..., kind="server")` for TAK Server links,
    filtered by `INGEST_FROM` (default local), `INGEST_UIDS` and the echo guard (`_forwarded`).
    A TAK Server carries other users' positions; never publish them by default. Kind "lan"
    (multicast) is published only for uids in INGEST_UIDS. Kind "local" without INGEST_UIDS is
    published only from loopback (`_from_loopback`). Events with RELAY_TAG are never published.
11. dispatch() tags every outgoing CoT with RELAY_TAG (loop protection between relays).
12. Field-package messages live in tools/field_package/lang.ps1 and tools/field_package/linux/lang.txt,
    with the same keys in fi and en (test_same_keys_in_fi_and_en, test_used_keys_exist, also for
    Linux). Never hard-code user text in the .ps1 or .sh installers. device.env is parsed, never sourced.
13. Unauthenticated listeners: GATEWAY_HTTP_BIND defaults to 127.0.0.1, also in the image;
    compose sets 0.0.0.0 in the container and publishes on the host's 127.0.0.1. TAK ports stay
    on all interfaces (TAK devices must reach them); the TCP server refuses clients beyond
    TAK_MAX_CLIENTS and TAK_MAX_CLIENTS_PER_IP. Demo HTTP ports are published on 127.0.0.1
    except the map view.
14. The release image is built once into an OCI archive in `image`, tested per architecture from
    that archive and pushed unchanged in `push-image`, after `image` and `install-template` pass.
    mediamtx is checked against the pinned SHA256 in the Dockerfile; update both together.
15. validate_cot accepts UTF-8 with exactly one `<event>`, no DTD. A UDP datagram that splits into
    more than one event is dropped whole. The TAK Server link is read and written by one thread.
16. A TLS truststore (TAK_SERVER_TRUST_P12 / TAK_SERVER_CA) replaces the OS CAs; never add it on
    top of them.

## Configuration surface

Env vars are documented in docs/en/relay.md (single source; update it when adding one).
Identity: GOAT_CERT/KEY/CA, GOAT_CERT_DIR (exclusive when set), GOAT_ORG, GOAT_ROUTER (tls/; else NOTES.md),
GOAT_LOCAL_ROUTER (tcp/). Mode: TAK_MODE (direct|multicast|server, docs/en/modes.md), TAK_LOCAL_OUTPUTS, TAK_MULTICAST_*.
Outputs: TAK_UDP_TARGETS, TAK_PORT, TAK_MAX_CLIENTS(_PER_IP), TAK_SERVER*, GATEWAY_CONFIG. Ingest:
GATEWAY_INGEST_ALL, TAK_INGEST, TAK_INGEST_FROM, TAK_INGEST_UIDS, TAK_UDP_IN_PORT. Ops: GATEWAY_HTTP_PORT,
GATEWAY_HTTP_BIND, GATEWAY_SYSTEM,
GATEWAY_WATCHDOG_S, GATEWAY_LOST_S. Video: GATEWAY_VIDEO*.

## Key spaces

| Key | Dir | Format |
| --- | --- | --- |
| `<org>/sensor/v1/**` | in | JSON telemetry {source,lat,lon,alt,heading,speed_kmh,type,phase,lost} |
| `*/tak/cot/v1/**` or `**` (INGEST_ALL) | in | any vendor; see backbone_cot.ALL_SOURCES |
| `<org>/tak/pli/v1/<uid>` | out | friendly CoT from TAK clients (TAK_INGEST=1) |
| `<org>/<system>/heartbeat/v1` | out | heartbeat JSON |
| `<org>/exercise/**`, `<org>/tak/cot/v1/EXERCISE.*` | demo out | sender.py |

Spec: docs/asyncapi-tak-gateway.yaml.

## Releasing

Tag vX.Y.Z = publish (docs/en/release.md). Never push a tag without the user's explicit consent.
__version__, docker-compose image tag and the newest CHANGELOG section must agree (check_release.py).

## Changing things

- New env var or behaviour: update docs/en/relay.md AND docs/fi/relay.md, CHANGELOG.md, tests.
- New relay module: add to APP_FILES; tests enforce it.
- New scenario: demo/scenarios/<name>.py using sender.Sender; document in docs/*/demo.md.
- New installer message: add the key to BOTH fi and en in lang.ps1 (Windows) or linux/lang.txt (Linux).
- Docs exist in two languages with the same file names (docs/en/X.md <-> docs/fi/X.md); keep
  them in sync. Finnish follows Kielitoimisto rules.
- tools/register_portal_topics.py --apply and anything publishing to the real fabric affect a
  shared network: do not run them without the user's explicit consent.
- No infrastructure addresses in the repo (router names, mesh IPs, internal hosts): the router
  comes from the bundle's NOTES.md or GOAT_ROUTER; goat_connect exits when neither names one.
- Docs and user-visible text name no events, places, people or national TAK variants; use
  WinTAK, ATAK or "TAK app". Vendor format names appear only in the "Recognised formats" table
  of docs/*/relay.md and in variable names (GATEWAY_SOURCES, GATEWAY_HYMOTS_INTERVAL_S).
- CHANGELOG lists what changed for users of the previous release; never what was removed from
  history or why.

## Unverified (do not claim otherwise)

ATAK connection package format and CoT `<video>` element on a real TAK client. Edge-AI demo CoT
is not exercise-labelled (README there says to set EDGE_COT_AFFIL=u).
TAK_MODE=multicast with real TAK devices (tested only over loopback); TAK_MODE=server against a
real TAK Server (tested against a local TLS server). The Linux field package on a real field device
(tested on the Ubuntu CI runner only, tests/ci_install_linux.sh).
