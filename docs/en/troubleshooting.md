# Troubleshooting

**Suomeksi:** [../fi/troubleshooting.md](../fi/troubleshooting.md)

Start with `python relay/doctor.py` (Docker: `docker compose exec tak-relay python3 relay/doctor.py`,
field package: `.\run.ps1 -CheckOnly`). It checks the bundle, slot, certificate expiry, NetBird, the
router, ports and the TAK Server, and prints a fix for each failure.

A running relay shows its state at <http://localhost:8088/>. `/status` gives the same as JSON:
`reasons` names what is wrong, `counters` show where messages go (`*_in_total`, `*_sent_total`,
`*_dropped_total{reason=…}`).

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `fabric link down`, `/healthz` 503 | Mesh down or router unreachable | `netbird status`: Management and Signal connected, nameservers 1/1. `goat doctor` |
| Router name does not resolve | Not on the mesh, or NetBird DNS not used | Reconnect NetBird. In Docker Desktop set `EFDI_ROUTER_IP` (mesh IP from `nslookup` on the host) |
| Relay logs `fabric unavailable (…)` repeatedly | Expired or wrong certificate, wrong router | `goat profile show`; check the bundle in `certs/`; set `GOAT_ROUTER` from the bundle |
| Exits with `cannot determine the org slot` | Certificate CN is not the slot | Set `GOAT_ORG=<slot id>` |
| `need exactly one … pair` / no bundle found | Several identities in one directory | Keep one cert/key pair per directory, or set `GOAT_CERT`/`GOAT_KEY`/`GOAT_CA` |
| Publish "works" but nobody receives | Key outside your slot (silently denied) | Publish only under `<slot>/…`; check with `goat flow <key>` |
| `/status` healthy, TAK shows nothing | UDP target wrong, firewall, TAK input not enabled | In Docker use `host.docker.internal`, not `127.0.0.1`. Open the TAK input port. Check `gateway_output_sent_total` |
| Markers appear and vanish | Source sends stale or past timestamps; clock skew | Check `gateway_cot_dropped_total{reason="already-stale"}`; sync the clock (NTP) |
| `no backbone samples for …` | Nothing published on the subscribed keys | `GATEWAY_INGEST_ALL=1` to see all vendors; check `/streams` |
| ATAK client disconnects | It stopped reading for 10 s | Expected protection; check the client's network |
| `port is already allocated` | Another process on 8087/8088/6971/8554/8080/7447 | Stop it, or change the host side of the port mapping |
| `output tcp_client:… not connected` | TAK Server unreachable or certificate refused | `doctor.py` names the cause; check `TAK_SERVER_P12`, the truststore and `TAK_SERVER_VERIFY_HOSTNAME` |
| `cannot open .p12 (wrong password?)` at start | Wrong `TAK_SERVER_P12_PASSWORD` | Fix the password; the truststore uses the same one unless `TAK_SERVER_TRUST_PASSWORD` is set |
| PLI not published, `reason="not-local"` / `"not-loopback"` / `"not-allowed"` / `"echo"` | By design: TAK Server users, devices on other machines (or in Docker, the host) without `TAK_INGEST_UIDS`, uids outside the list, markers the relay itself sent | Add the device uid to `TAK_INGEST_UIDS` |
| `PermissionError` on the key (Linux) | Container runs as UID 10001 | `chmod 640` the key and give group 10001 read, or set `user: "0"` for the service |
| Heartbeat not visible in the portal | System name not registered | `python tools/register_portal_topics.py --add-system <name> --apply` |
| Field device: autostart missing | Scheduled tasks blocked by policy | The installer falls back to the Startup folder; check its output |
