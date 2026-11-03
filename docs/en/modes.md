# Choose a mode

**Suomeksi:** [../fi/modes.md](../fi/modes.md)

`TAK_MODE` decides how TAK devices get the backbone picture. Pick one per relay:

1. **Do you have a TAK Server?** → `server`
2. **Is the network closed and only yours** (e.g. a vehicle Wi-Fi)? → `multicast`
3. **Otherwise** → `direct` (the default)

| | `direct` | `multicast` | `server` |
| --- | --- | --- | --- |
| **For** | This machine or a few named devices | A closed tactical LAN | An organisation with a TAK Server |
| **What to set in TAK** | One input port: UDP 6969 (TAK app), 4242 (WinTAK) or TCP 8087 | Nothing | Nothing; devices are already on the server |
| **Who sees the backbone** | Only those devices | **Everyone on the LAN segment** | Every user on the server |
| **Whose position is published** (`TAK_INGEST=1`) | Local devices (or `TAK_INGEST_UIDS`) | Only uids in `TAK_INGEST_UIDS` | Nobody by default |
| **Docker** | Yes | Linux host network only | Yes |
| **Required** | — | — | `TAK_SERVER` and its .p12 files |

## direct

CoT goes by UDP to `TAK_UDP_TARGETS` (or `TAK_HOST:TAK_UDP_PORT`), and ATAK/WinTAK can connect to
the TCP server on `TAK_PORT` (8087). Only the devices you point at the relay get the picture.
Works everywhere, including Docker Desktop.

## multicast

CoT goes to the TAK SA multicast group `239.2.3.1:6969`, which ATAK, WinTAK and iTAK listen to by
default, so nothing has to be set in TAK. The TCP server on `TAK_PORT` stays on for devices that
cannot use multicast.

- **Everyone on the same LAN segment gets the backbone picture.** Use it only on a closed network
  of your own, never on an office or shared Wi-Fi.
- The relay also hears every device's own position on the group. Those are published only for the
  uids in `TAK_INGEST_UIDS`; without the list nobody heard on the LAN is published.
- Multicast stays on the segment (`TAK_MULTICAST_TTL=1`) and is blocked by many Wi-Fi and
  corporate networks. With several networks (NetBird, Wi-Fi, Ethernet) set `TAK_MULTICAST_IF` to the
  LAN interface's IPv4 address.
- Docker: `docker compose -f docker-compose.yml -f docker-compose.multicast.yml up -d` on a Linux
  host. Docker Desktop on Mac or Windows does not pass multicast; use the field package there.

| Variable | Default | Meaning |
| --- | --- | --- |
| `TAK_MULTICAST_GROUP` | `239.2.3.1:6969` | Group and port |
| `TAK_MULTICAST_IF` | OS default | IPv4 address of the LAN interface |
| `TAK_MULTICAST_TTL` | `1` | Router hops; 1 = this segment only |

## server

The relay streams to the TAK Server (`TAK_SERVER`, see [relay: TAK Server](relay.md#tak-server)),
and every user on the server sees the backbone. One relay per TAK Server is enough.

- The local UDP and TCP outputs are off, so devices on the server do not get every marker twice.
  `TAK_LOCAL_OUTPUTS=1` turns them back on.
- Positions of TAK Server users are never published to the backbone, unless
  `TAK_INGEST_FROM=local,server`.
- The relay refuses to start without `TAK_SERVER`.

## In every mode

- Every CoT the relay sends carries `<__efdi_relay/>` in its `<detail>`. No relay publishes an
  event with that tag, so two relays on the same LAN or TAK Server cannot loop markers back to the
  backbone (`gateway_ingest_dropped_total{reason="relayed"}`).
- `TAK_SERVER` can be added in `direct` and `multicast` too, to feed a TAK Server as well.
- `python relay/doctor.py` checks the chosen mode: a missing `TAK_SERVER`, joining the multicast
  group, the TAK Server handshake.
- The status page (`:8088/`) and `/status` show the mode.

## Choosing it

| Where | How |
| --- | --- |
| Field package | `install.cmd` asks: language first, then the mode and its details. Preset with `make_relay_package.py --lang en --mode server …` |
| Docker | `TAK_MODE=…` in `.env`; multicast also needs `docker-compose.multicast.yml` |
| Native | `TAK_MODE=… python relay/tak_gateway.py` |

## Verified

`direct` is verified against the real fabric and TAK clients. `multicast` is tested with real
multicast over the loopback interface, and `server` against a local TLS server with a client
certificate; neither yet with real TAK devices or a real TAK Server.
