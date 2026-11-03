# The demo

**Suomeksi:** [../fi/demo.md](../fi/demo.md)

The demo shows the relay end to end: simulated tracks enter the backbone, the relay turns them
into TAK markers, and a live map shows the same tracks in a browser. Nothing in `demo/` is
needed to run the relay.

## Parts

| Part | File | Role |
| --- | --- | --- |
| **Scenarios** | `demo/scenarios/swarm_orbit.py` | 4 UAVs from the east, orbit over a target area, 10-min cycle |
| | `demo/scenarios/strike_package.py` | 10 UAVs start area → target, different speeds and altitudes |
| | `demo/scenarios/mass_raid.csv` | Mass attack start area → target, played from the map's control panel |
| **Sender** | `demo/sender.py` | The only path for demo data into the backbone; adds the exercise labels |
| **Viewers** | `demo/live_map.py` | Leaflet map on `:8080`, control panel on `/control` |
| | `demo/tools/live_monitor.py` | Terminal list of exercise and sensor tracks |
| | `demo/tools/read_cot.py` | Prints the CoT stream from the relay's TCP port |
| | `demo/tools/verify_efdi.py` | Checks that an mTLS session to the fabric opens |
| **Infrastructure** | `demo/local_router.py` | Local Zenoh router for offline use |
| | `demo/run-backbone-demo.ps1` | One-command launcher on Windows |
| | `demo/setup-certs.ps1` | Copies a bundle into `certs/` |
| **Edge-AI demo** | `demo/edge_ai/` | Detection + geolocation → CoT, see its [README](../../demo/edge_ai/README.md) |

## The sender contract

Scenarios only compute positions and call `Sender.track(uid, lat, lon, alt, heading, speed_kmh,
phase=…, cot_type=…, lost=…, **extra)`. The sender publishes:

| Key | Content |
| --- | --- |
| `<slot>/exercise/<scenario>/v1/<uid>` | JSON with `"exercise": true`, `"classification": "SIMULATED"`, a label, `seq`, `ts_ms` |
| `<slot>/tak/cot/v1/EXERCISE.<uid>` | CoT marker, callsign `EXERCISE <uid>`, remarks starting with `SIMULATED` |

Rules every scenario follows:

- Publish only through `demo/sender.py`. Never write demo data to `<slot>/sensor/v1/**`.
- The relay brings the markers to TAK; scenarios do not send to TAK clients directly.
- Lost tracks (`lost=True`) publish JSON only; the TAK marker goes stale after 15 s.

A new scenario is a short script:

```python
import sender
with sender.open_session("my-scenario") as s:
    out = sender.Sender(s, "my-scenario")
    out.track("uav-1", 61.0, 25.0, alt=300, heading=90, speed_kmh=200, phase="ingress")
```

## Running it

### Windows, one command

```powershell
.\demo\run-backbone-demo.ps1 -BundleDir C:\path\to\bundle   # first run copies certs
.\demo\run-backbone-demo.ps1                                # later runs
.\demo\run-backbone-demo.ps1 -NoSwarm | -EdgeAI | -EdgeApi | -Stop
```

The launcher checks the mesh, starts the relay with demo settings (CoT to TAK app 6969 and WinTAK
4242, PLI ingest and video on), the demo profile, and the strike-package scenario natively. Logs go to
`logs/`.

### Any OS

```bash
docker compose --profile demo up -d        # relay + local router + live map + drone swarm
python demo/scenarios/strike_package.py    # needs: pip install -r relay/requirements.txt
```

### Offline (no certificates, no mesh)

Leave `certs/` empty. Every component then uses the local router (`zenoh-router` service on
`:7447`) and the namespace `local/…`. The relay, map and scenarios behave exactly as on the
fabric, without the heartbeat.

## Viewing

- **Map:** <http://localhost:8080>. **Control panel:** `/control`: inject a single track, start
  a scripted scenario, or drag and drop a mission CSV/JSON (`demo/scenarios/mass_raid.csv`,
  example at `/example.csv`). Injected tracks go through the sender.
- **TAK:** WinTAK takes CoT on UDP 4242, TAK app on 6969, ATAK by TCP `<host>:8087`.
- **Relay:** `http://localhost:8088/status` and `/streams`.
- **Terminal:** `python demo/tools/live_monitor.py`.

## Before a demo on the shared fabric

- [ ] `netbird status`: Management and Signal connected, nameservers available.
- [ ] `goat doctor` passes (or `python demo/tools/verify_efdi.py`).
- [ ] `curl localhost:8088/status` → `"healthy": true`.
- [ ] Callsigns in TAK start with `EXERCISE`.
- [ ] Edge-AI demo: `EDGE_COT_AFFIL=u`, so its markers are not shown as confirmed hostiles.
- [ ] `.\demo\run-backbone-demo.ps1 -Stop` afterwards, so simulated data does not keep flowing.
