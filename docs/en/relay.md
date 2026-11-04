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
| `identity.py` | Finds the certificate bundle, the org slot and the router (stdlib only) |
| `tak_links.py` | TAK-side settings: UDP targets, TAK Server link and its TLS (.p12 or PEM) |
| `doctor.py` | Preflight check: `python relay/doctor.py` |
| `status_page.py` | Status page at `/` |
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
| `GOAT_CERT_DIR` | `<repo>/certs`, `./certs`, `/certs`, then `~/Downloads/efdi-onboarding-*` | Bundle directory. When set, it is the only one searched |
| `GOAT_ORG` | certificate CN | Org slot. Needed only if the CN is not the slot |
| `GOAT_ROUTER` | `Router endpoint` in the bundle's `NOTES.md`, else `tls/router.example:7447` | mTLS router |
| `GOAT_LOCAL_ROUTER` | `tcp/localhost:7447` | Router used when no bundle is found |
| `GOAT_LEASE_MS` | `60000` | Zenoh lease; long, because relayed mesh paths stall |

A bundle directory must hold exactly one `<prefix>-cert.pem` + `<prefix>-key.pem` pair and a CA
root (`efdi-ca-root.pem`). With a certificate but no resolvable slot the relay refuses to start,
because writes outside your slot would be dropped without an error.

An unpacked onboarding bundle in `~/Downloads/efdi-onboarding-*` is used when no other bundle is
found and exactly one such directory exists. With several, set `GOAT_CERT_DIR`.

## Backbone → TAK

| Variable | Default | Meaning |
| --- | --- | --- |
| `GATEWAY_INGEST_ALL` | `0` natively, `1` in compose | `1`: subscribe `**` and convert every recognised format. `0`: only `GATEWAY_COT_KE` |
| `GATEWAY_COT_KE` | `*/tak/cot/v1/**` | Ready-made CoT from any vendor (when `GATEWAY_INGEST_ALL=0`) |
| `GATEWAY_SOURCES` | all | Subset of `xml,geotrack,consilium,mavlink,hymots,orion,adsb,alerts,roi,proto` ([formats](#recognised-formats)) |
| `GATEWAY_HYMOTS_INTERVAL_S` | `10` | Minimum interval per track of the `hymots` source |
| `XV_MAX_HZ_PER_UID` | `2` | Rate limit per uid for `GATEWAY_COT_KE` traffic |
| `COT_TYPE` | `a-h-A-M-F-Q` | Fallback CoT type |

Your own JSON telemetry on `<slot>/sensor/v1/**` (`{source, lat, lon, alt, heading, speed_kmh,
type, phase, lost}`) is always converted. `"lost": true` sends an expired marker so TAK removes
the track. Keys containing `video`, `keyframe` or `asterix-raw`, heartbeats and the relay's own
PLI are never converted.

### Recognised formats

| Source (`GATEWAY_SOURCES`) | Payload |
| --- | --- |
| `xml` | Ready-made CoT `<event>` on any key, forwarded as is after validation |
| `geotrack` | JSON with schema `goat.geo.track.v1` |
| `consilium` | Consilium JSON: `ci_uuid`, `location.latitude/longitude` |
| `mavlink` | MAVLink JSON: `mavpackettype` `GLOBAL_POSITION_INT` |
| `hymots` | HYMOTS JSON: `agents[]` with `location` and `sidc` |
| `orion` | Orion JSON: `entityId`, `location.position` |
| `adsb` | ADS-B JSON: `kind` `uk-adsb-assessment`, `aircraft[]` |
| `alerts` | Alert JSON: `alert_text`, `event.locations[]` |
| `roi` | Region of interest: `MAV_CMD_DO_SET_ROI_LOCATION` |
| `proto` | Protobuf tracks |

## Outputs

`TAK_MODE` picks the set-up; see [choose a mode](modes.md). The variables below fine-tune it.

| Variable | Default | Meaning |
| --- | --- | --- |
| `TAK_MODE` | `direct` | `direct`, `multicast` or `server` |
| `TAK_LOCAL_OUTPUTS` | `0` | `server` mode: `1` keeps the UDP and TCP outputs too |
| `TAK_MULTICAST_GROUP`, `TAK_MULTICAST_IF`, `TAK_MULTICAST_TTL` | `239.2.3.1:6969`, OS default, `1` | `multicast` mode, see [modes](modes.md#multicast) |
| `TAK_UDP_TARGETS` | `TAK_HOST:TAK_UDP_PORT` | `host:port[,host:port…]` CoT by UDP. Default port 6969; WinTAK listens on 4242 |
| `TAK_HOST`, `TAK_UDP_PORT` | `127.0.0.1`, `6969` | Single UDP target (older form) |
| `TAK_PORT` | `8087` | TCP server for ATAK/WinTAK streaming clients |
| `TAK_MAX_CLIENTS` | `64` | Most TCP clients at once; further connections are refused |
| `TAK_SERVER` | — | `host[:port]` of a TAK Server to stream to (see below) |
| `GATEWAY_CONFIG` | — | JSON file replacing all of the above |

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

## TAK Server

With `TAK_SERVER` set, the relay also streams to a TAK Server, and every user on that server sees
the backbone picture. One relay per TAK Server is enough; devices on the server need no relay of
their own.

| Variable | Default | Meaning |
| --- | --- | --- |
| `TAK_SERVER` | — | `host[:port]`, port 8089 if omitted |
| `TAK_SERVER_TLS` | `1` (`0` on port 8087) | TLS with a client certificate |
| `TAK_SERVER_P12`, `TAK_SERVER_P12_PASSWORD` | — | Client certificate issued by the TAK Server (.p12) |
| `TAK_SERVER_TRUST_P12`, `TAK_SERVER_TRUST_PASSWORD` | —, the P12 password | Truststore with the TAK Server CA (.p12) |
| `TAK_SERVER_CERT`, `TAK_SERVER_KEY`, `TAK_SERVER_CA` | — | PEM files instead of .p12 |
| `TAK_SERVER_VERIFY_HOSTNAME` | `1` | `0` when the server certificate does not name the address you use |

.p12 files need `cryptography` (in `relay/requirements.txt` and the Docker image). The decrypted
key is never left on disk. In Docker, put the files in `certs/tak/` and use `/certs/tak/…` paths.
A wrong password or file stops the relay at start with a clear message; `doctor.py` tests the
handshake. Users on the TAK Server are never published to the backbone (next section).

Do not feed the same devices both directly (UDP/`:8087`) and through the TAK Server: they would
get every marker twice. Choose one path per device.

## TAK → backbone (PLI)

| Variable | Default | Meaning |
| --- | --- | --- |
| `TAK_INGEST` | `0` | `1`: publish friendly CoT to `<slot>/tak/pli/v1/<uid>` |
| `TAK_INGEST_TYPES` | `a-f-` | Comma-separated type prefixes accepted |
| `TAK_INGEST_FROM` | `local` (`multicast` mode: `local,lan`) | Which links may publish: `local` (UDP input, clients on `:8087`), `lan` (multicast group, only with `TAK_INGEST_UIDS`), `server` (TAK Server link). Comma-separated |
| `TAK_INGEST_UIDS` | empty | Comma-separated uids allowed to publish (e.g. `ANDROID-abc123`). Empty = only TAK apps on this machine (loopback) |
| `TAK_UDP_IN_PORT` | `0` (compose: `6971`) | UDP port for CoT from TAK clients (their UDP output) |

Events from TCP clients connected to `:8087` are read as well. At most 1 Hz per uid; tasking
(`t-*`) and non-friendly types are never published. This writes to the shared backbone, so it is
off by default.

Only your own devices are published:

- **TAK Server users stay on the TAK Server.** A `tcp_client` link carries every user on that
  server. Its events go to TAK only, never to the backbone, unless `TAK_INGEST_FROM=local,server`.
- **This machine only, unless listed.** Without `TAK_INGEST_UIDS` only events from this machine
  (127.0.0.1) are published. Anyone else on the network could otherwise put positions on the
  backbone under your slot. To publish a device on another machine, list its uid.
- **Allowlist.** With `TAK_INGEST_UIDS` set, only those uids are published, even if a terminal
  forwards other users' positions. A uid is what the device says it is, so the list limits
  mistakes, not a deliberate forger: keep ports 6971 and 8087 off untrusted networks.
- **No echo.** A uid the relay itself sent to TAK in the last 60 s is not published back.

In Docker, packets from the host do not come from 127.0.0.1, so `TAK_INGEST=1` there needs
`TAK_INGEST_UIDS`.

Drops are counted in `gateway_ingest_dropped_total{reason="not-local"|"not-loopback"|"not-allowed"|"echo"|"relayed"}` (`relayed`: the
event carries another relay's tag, see [modes](modes.md#in-every-mode));
`/status` shows `ingest_from` and `ingest_uids`.

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

The HTTP port listens on `GATEWAY_HTTP_BIND`, by default `127.0.0.1` (this machine only), because
it has no authentication and `/api/sample` returns backbone payloads. The Docker image sets
`0.0.0.0` inside the container and `docker-compose.yml` publishes the port on the host's
`127.0.0.1` only. To reach it from another machine, set `GATEWAY_HTTP_BIND=0.0.0.0` (native) or
change the compose mapping, and limit access with a firewall.

| Path | Content |
| --- | --- |
| `/` | Status page for people: health, reasons, outputs, traffic, drops |
| `/healthz` | 200 when the fabric link is up, else 503 (Docker `HEALTHCHECK`) |
| `/metrics` | Prometheus text: per-output sent/errors/dropped, drops by reason, types seen |
| `/status` | JSON: health and reasons, version, org, system, counters, outputs, ingest settings, video |
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
- **Ports 8087, 8088, 6971 and 8554 have no authentication.** This is how TAK's plain CoT
  inputs work: TAK devices on the network must reach 8087, 6971 and 8554, so those listen on
  all interfaces. 8088 (`/api/sample` returns buffered backbone payloads) listens on this machine
  only by default. Keep the relay on a network you trust, and firewall the ports elsewhere.
- **TCP clients are capped** at `TAK_MAX_CLIENTS` (64); further connections are refused
  (`gateway_output_rejected_total`).
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
- The TAK Server link is tested against a local TLS server with a client certificate, not yet
  against a real TAK Server.
