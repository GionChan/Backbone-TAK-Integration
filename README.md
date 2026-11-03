# EFDI TAK relay

[![Tests](https://github.com/GionChan/Backbone-TAK-Integration/actions/workflows/tests.yml/badge.svg)](https://github.com/GionChan/Backbone-TAK-Integration/actions/workflows/tests.yml)

**Suomeksi:** [README.fi.md](README.fi.md) · **For AI agents:** [AGENTS.md](AGENTS.md)

A two-way bridge between the **EFDI goat fabric** (Zenoh over mTLS on a NetBird mesh) and
**TAK clients** (WinTAK, ATAK, TAK Server).

- **Backbone → TAK.** Every recognisable position message on the backbone becomes a CoT marker:
  ready-made CoT XML from any vendor, `goat.geo.track.v1`, MAVLink, Consilium, HYMOTS, Orion,
  ADS-B, protobuf tracks and your own JSON telemetry. Messages are validated, rate-limited and
  de-duplicated before they reach a client.
- **TAK → backbone.** Optional: friendly position reports (PLI) from your own TAK users are
  published to the backbone.
- **Operations.** Mandatory fabric heartbeat, `/healthz`, Prometheus `/metrics`, `/status`, a
  `/streams` view of live backbone traffic, a watchdog that restarts the relay when the link or
  the feed dies, and an optional video restream (RTSP) to TAK.

## What is in this repository

| Path | What it is | Use it for |
| --- | --- | --- |
| [`relay/`](relay/) | **The product: the TAK relay** (`tak_gateway.py` and its modules) | Running against the real fabric |
| [`tools/`](tools/) | Field-device package builder, portal topic registration | Deploying the relay |
| [`demo/scenarios/`](demo/scenarios/) | **Demo scenarios**: drone swarm, strike package, mass-raid CSV | Showing the system |
| [`demo/sender.py`](demo/sender.py) | **Demo sender**: the only way demo data enters the backbone; labels everything SIMULATED | Writing new scenarios |
| [`demo/`](demo/) (rest) | Live map, local router, launcher, monitor, edge-AI demo | Showing the system |
| [`tests/`](tests/) | Unit tests and a local end-to-end test | Development |
| [`docs/`](docs/) | Documentation in [English](docs/en/) and [Finnish](docs/fi/), AsyncAPI spec | Reading |

The relay never imports anything from `demo/`. Demo data is always exercise-labelled and lives in
its own namespace, so it cannot be mistaken for real sensor data.

## Quick start: the relay

Prerequisites: NetBird connected to the EFDI mesh, Docker, and your onboarding bundle.

```bash
mkdir certs && cp /path/to/bundle/{*-cert.pem,*-key.pem,efdi-ca-root.pem} certs/
cp .env.example .env           # optional: adjust TAK targets, system name, ingest
docker compose up -d           # starts the relay only
curl localhost:8088/status     # "healthy": true once the fabric link is up and data flows
```

Point your TAK client at the relay:

- **TAK app:** UDP input 6969 on the Docker host (default target).
- **WinTAK:** add `host.docker.internal:4242` to `TAK_UDP_TARGETS` in `.env`.
- **ATAK / WinTAK over TCP:** TAK Server → TCP streaming → `<relay-host>:8087`.

Field devices without Docker: build a self-installing package with
`python tools/make_relay_package.py --system <name>`; see [field package](docs/en/field-package.md).

## Quick start: the demo

```powershell
.\demo\run-backbone-demo.ps1 -BundleDir C:\path\to\bundle   # Windows, first run
```

or, on any OS:

```bash
docker compose --profile demo up -d          # relay + local router + live map + drone swarm
python demo/scenarios/strike_package.py      # a second scenario from this machine
```

Open the map at <http://localhost:8080>; scenarios and CSV playback are at `/control`. Without
certificates everything runs against the local router, offline. See the [demo guide](docs/en/demo.md).

## Documentation

| | English | Suomi |
| --- | --- | --- |
| Overview and architecture (plain language) | [overview](docs/en/overview.md) | [yleiskuva](docs/fi/overview.md) |
| Relay: configuration, topics, operations, security | [relay](docs/en/relay.md) | [relay](docs/fi/relay.md) |
| Demo: scenarios, sender, viewers | [demo](docs/en/demo.md) | [demo](docs/fi/demo.md) |
| Field-device package (Windows, no Docker) | [field package](docs/en/field-package.md) | [kenttäpaketti](docs/fi/field-package.md) |
| Troubleshooting | [troubleshooting](docs/en/troubleshooting.md) | [vianetsintä](docs/fi/troubleshooting.md) |
| Interface spec | [`docs/asyncapi-tak-gateway.yaml`](docs/asyncapi-tak-gateway.yaml) | |
| Changes | [CHANGELOG](CHANGELOG.md) | |

## Development

```bash
pip install -r relay/requirements.txt
python -m unittest discover -s tests                  # unit tests
docker compose --profile demo up -d zenoh-router
python tests/e2e_gateway.py                           # end-to-end against the local router
```

CI runs the unit tests on Windows and Linux for every push and pull request to `main`.

## Status

The relay path
(install → healthy against the real fabric → CoT from several vendors → uninstall) has been
verified on Windows field devices. Not verified on a real TAK client: the ATAK connection
package and the CoT `<video>` element (see [relay](docs/en/relay.md#known-limitations)).

## License

Apache License 2.0, see [LICENSE](LICENSE).
