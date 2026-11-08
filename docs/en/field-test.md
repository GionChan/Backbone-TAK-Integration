# Field test

**Suomeksi:** [../fi/field-test.md](../fi/field-test.md)

What CI cannot test: real TAK devices, two relays over the real fabric, a Linux field device. Run
this on an exercise network before using marker sharing or the Linux package in operations. Tick
each line, and note the relay's version (`/status`) and the TAK app versions.

## Set-up

| | Relay A | Relay B |
| --- | --- | --- |
| Slot | Organisation 1 | Organisation 1 or another one (steps 8–9 need another one) |
| Settings | `TAK_SHARE_MARKERS=1`, `TAK_INGEST=1` | Defaults |
| TAK device | ATAK or WinTAK, connected to relay A | ATAK or WinTAK, connected to relay B |

Markers also go between two relays of the same organisation. Positions do not: a relay does not
show the positions its own slot publishes, so steps 8–9 need relay B in another slot.

Before starting, on both: `python relay/doctor.py` (field package: `run.ps1 -CheckOnly` or
`./run.sh --check-only`) has no FAIL, and `http://localhost:8088/` says **Healthy**.

## Markers and drawings (A → B)

| # | On device A | Expected on device B | If not, look at relay A |
| --- | --- | --- | --- |
| 1 | Place a hostile marker | Appears within a few seconds | `/metrics`: `gateway_markers_published_total` grows; else `gateway_ingest_dropped_total{reason=...}` |
| 2 | Drag the marker to a new place | Moves to the new place | Same; `reason="relayed"` means A sent the marker back to its own device (report it) |
| 3 | Move it twice within one second | Ends at the last place | `gateway_ingest_deferred_total` grows |
| 4 | Draw a line or an area | Appears | As 1 |
| 5 | Delete the marker | Disappears | `gateway_marker_deletes_published_total`; `reason="delete-unknown"` or `"not-allowed"` |
| 6 | Send a GeoChat message | **Does not** arrive | `reason="chat"` grows |
| 7 | Device A's own marker on device A | Is shown **once**, not twice | `gateway_cot_dropped_total{reason="own-marker"}` grows |

## Back the other way (B → A)

| # | Check | Expected |
| --- | --- | --- |
| 8 | Device A sees relay B's position (with `TAK_INGEST=1` on B) | Shown on A |
| 9 | Device A shares back a marker it received from B (e.g. re-sends it) | Relay A does not publish it: `reason="relayed"` or `"echo"` |

## Restart (relay A)

| # | Step | Expected |
| --- | --- | --- |
| 10 | Restart relay A, then delete a marker shared before the restart | Stays on B until it goes stale (known limitation); after one edit of the marker, the deletion goes through |

## Linux field device

| # | Step | Expected |
| --- | --- | --- |
| 11 | `./install.sh --at-boot`, then reboot without signing in | `http://localhost:8088/` answers |
| 12 | A TAK device on the network connects to TCP 8087 | Gets the backbone picture (open the port in the firewall if needed) |
| 13 | `./uninstall.sh` | No relay process, port 8088 free |

## Report

For each failed line: the step, what happened, relay A's `/status` and the relevant
`/metrics` lines, the TAK app and its version.
