# The TAK relay

**Suomeksi:** [../fi/relay.md](../fi/relay.md)

`relay/tak_gateway.py` and the modules next to it. Python 3.10+, one required dependency
(`eclipse-zenoh==1.9.0`). Runs in Docker (`docker compose up -d`) or natively
(`python relay/tak_gateway.py`, or the [field package](field-package.md)).

## Modules

| File | Role |
| --- | --- |
| `tak_gateway.py` | Entry point: subscriptions, outputs, PLI ingest, HTTP endpoints, watchdog |
| `goat_connect.py` | Zenoh session config: mTLS to the fabric, or a local router without certificates |
| `identity.py` | Finds the certificate bundle and the org slot (stdlib only) |
| `backbone_cot.py` | Recognises vendor formats and converts them to CoT |
| `cot_guard.py` | CoT validation and per-key rate limiter |
| `symbology.py` | CoT type (affiliation, dimension) from text, SIDC or kinematics |
| `heartbeat.py` | The mandatory fabric heartbeat |
| `stream_view.py` | `/streams` page: live backbone traffic, previews |
| `video_relay.py` | Backbone MPEG-TS → MediaMTX → RTSP, CoT `<video>` marker |
| `gateway_core.py` | Pure helpers: CoT stream splitting, Prometheus text, ATAK package |
| `make_atak_package.py` | CLI: ATAK/WinTAK connection package (`<host> [port] [out.zip]`) |

## Identity and connection

| Variable | Default | Meaning |
| --- | --- | --- |
| `GOAT_CERT`, `GOAT_KEY`, `GOAT_CA` | — | Explicit PEM paths (all three) |
| `GOAT_CERT_DIR` | `<repo>/certs`, `./certs`, `/certs` | Bundle directory. When set, it is the only one searched |
| `GOAT_ORG` | certificate CN | Org slot. Needed only if the CN is not the slot |
| `GOAT_ROUTER` | `tls/router.example:7447` | mTLS router. Take it from your bundle if it differs |
| `GOAT_LOCAL_ROUTER` | `tcp/localhost:7447` | Router used when no bundle is found |
| `GOAT_LEASE_MS` | `60000` | Zenoh lease; long, because relayed mesh paths stall |

A bundle directory must hold exactly one `<prefix>-cert.pem` + `<prefix>-key.pem` pair and a CA
root (`efdi-ca-root.pem`). With a certificate but no resolvable slot the relay refuses to start,
because writes outside your slot would be dropped without an error.

## Backbone → TAK

| Variable | Default | Meaning |
| --- | --- | --- |
| `GATEWAY_INGEST_ALL` | `0` natively, `1` in compose | `1`: subscribe `**` and convert every recognised format. `0`: only `GATEWAY_COT_KE` |
| `GATEWAY_COT_KE` | `*/tak/cot/v1/**` | Ready-made CoT from any vendor (when `GATEWAY_INGEST_ALL=0`) |
| `GATEWAY_SOURCES` | all | Subset of `xml,geotrack,consilium,mavlink,hymots,orion,adsb,alerts,roi,proto` |
| `GATEWAY_HYMOTS_INTERVAL_S` | `10` | Minimum interval per HYMOTS track |
| `XV_MAX_HZ_PER_UID` | `2` | Rate limit per uid for `GATEWAY_COT_KE` traffic |
| `COT_TYPE` | `a-h-A-M-F-Q` | Fallback CoT type |

Your own JSON telemetry on `<slot>/sensor/v1/**` (`{source, lat, lon, alt, heading, speed_kmh,
type, phase, lost}`) is always converted. `"lost": true` sends an expired marker so TAK removes
the track. Keys containing `video`, `keyframe` or `asterix-raw`, heartbeats and the relay's own
PLI are never converted.

## Outputs

| Variable | Default | Meaning |
| --- | --- | --- |
| `TAK_UDP_TARGETS` | `TAK_HOST:TAK_UDP_PORT` | `host:port[,host:port…]` CoT by UDP. TAK app 6969, WinTAK 4242 |
| `TAK_HOST`, `TAK_UDP_PORT` | `127.0.0.1`, `6969` | Single UDP target (older form) |
| `TAK_PORT` | `8087` | TCP server for ATAK/WinTAK streaming clients |
| `GATEWAY_CONFIG` | — | JSON file replacing the above, also for TAK Server TCP/TLS clients |

```json
{"outputs": [{"type": "udp", "host": "host.docker.internal", "port": 6969},
             {"type": "tcp_server", "port": 8087},
             {"type": "tcp_client", "host": "tak.example", "port": 8089,
              "tls": {"cert": "c.pem", "key": "k.pem", "ca": "ca.pem", "verify_hostname": true}}],
 "ingest": false}
```

Each TCP client has its own queue (1000 events) and writer thread. A client that stops reading
overflows only its own queue and is dropped after 10 s without progress
(`gateway_output_dropped_total`).

## TAK → backbone (PLI)

| Variable | Default | Meaning |
| --- | --- | --- |
| `TAK_INGEST` | `0` | `1`: publish friendly CoT to `<slot>/tak/pli/v1/<uid>` |
| `TAK_INGEST_TYPES` | `a-f-` | Comma-separated type prefixes accepted |
| `TAK_UDP_IN_PORT` | `0` (compose: `6971`) | UDP port for CoT from TAK clients (e.g. TAK app output) |

Events from TCP clients connected to `:8087` are read as well. At most 1 Hz per uid; tasking
(`t-*`) and non-friendly types are never published. This writes to the shared backbone, so it is
off by default.

## Heartbeat and health

The relay publishes `<slot>/<GATEWAY_SYSTEM>/heartbeat/v1` every `GOAT_HEARTBEAT_INTERVAL_S`
(60 s) when connected to the real fabric: `{key, system, status, version, sent_at, seq,
interval_seconds}`. `status` is `ok` only when the fabric link is up, a sample arrived in the
last 120 s and every output is connected; otherwise `degraded`. `GATEWAY_SYSTEM` (default
`tak-gateway`) must be registered in the portal (`tools/register_portal_topics.py`).
`GATEWAY_HEARTBEAT=0` turns it off; `GATEWAY_VERSION` overrides the reported version.

Watchdog: the process exits (Docker or the field launcher restarts it) when the fabric link has
been down for `GATEWAY_LOST_S` (300 s) or no sample has arrived for `GATEWAY_WATCHDOG_S` (300 s).

## HTTP endpoints (`GATEWAY_HTTP_PORT`, default 8088)

| Path | Content |
| --- | --- |
| `/healthz` | 200 when the fabric link is up, else 503 |
| `/metrics` | Prometheus text: per-output sent/errors/dropped, drops by reason, types seen |
| `/status` | JSON: health and reasons, counters, outputs, ingest, video |
| `/streams` | Browser view of live backbone traffic per key group, with image/video preview |
| `/api/streams`, `/api/sample?g=`, `/api/preview?g=`, `/api/video?g=` | Data behind `/streams` |

## Video (opt-in)

`GATEWAY_VIDEO=1` (needs `GATEWAY_INGEST_ALL=1`) restreams backbone MPEG-TS: one ffmpeg process
per camera pushes to MediaMTX, TAK clients pull `rtsp://GATEWAY_VIDEO_HOST:GATEWAY_VIDEO_PORT/<cam>`
and get a CoT marker with a `<video>` element ("Play Video"). `GATEWAY_VIDEO_HOST` is the address
TAK clients use, never `host.docker.internal`. `GATEWAY_VIDEO_IDLE_S` (120) stops an idle
camera; `GATEWAY_VIDEO_REPUBLISH_S` (30) refreshes the marker. ffmpeg and mediamtx are in the
Docker image.

## Security

- **Certificates** (`certs/`, `*.pem`, `*.key`, `*.cbor`) and **field packages** (`dist/`) are
  git-ignored: they hold the private key. Never commit or share them.
- **Ports 8087, 8088, 6971 and 8554 have no authentication.** `/api/sample` returns buffered
  backbone payloads. Expose them only on the local machine or a trusted network, and firewall
  them elsewhere.
- **Least privilege on the fabric.** The relay reads widely (`**` with `GATEWAY_INGEST_ALL=1`)
  but writes only heartbeats and, with `TAK_INGEST=1`, PLI under your own slot.
- **Untrusted input.** Other vendors' CoT is validated before forwarding (no DTD, size and
  coordinate limits, stale check); field values in generated CoT are XML-escaped.
- **Container** runs as UID 10001. On Linux the mounted key must be readable by it.

## Known limitations

- The ATAK connection package (`make_atak_package.py`) and the CoT `<video>` element are written
  from TAK documentation and not yet verified on a real TAK client. The MediaMTX pipeline itself
  is verified end to end.
- Field devices share the organisation certificate; only `GATEWAY_SYSTEM` differs per device.
