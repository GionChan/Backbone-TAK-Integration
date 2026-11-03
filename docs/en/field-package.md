# Field-device package (Windows, no Docker)

**Suomeksi:** [../fi/field-package.md](../fi/field-package.md)

For devices with a TAK terminal but no Docker. One self-installing ZIP runs
the same `relay/tak_gateway.py` natively.

## Build

```bash
python tools/register_portal_topics.py --add-system field-relay-01 --apply   # register the heartbeat first
python tools/make_relay_package.py --system field-relay-01                   # → dist/field-relay-01-tak-relay.zip
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--system` | required | Unique device name: `GATEWAY_SYSTEM`, heartbeat topic, file name |
| `--cert-dir` | `./certs` | Bundle to include (one cert/key pair + CA) |
| `--tak-host`, `--tak-udp-port` | `127.0.0.1`, `6969` | Where the TAK terminal listens for CoT |
| `--tak-port` | `8087` | TCP stream port |
| `--tak-udp-in-port` | `6971` | UDP port for PLI from the terminal |
| `--no-ingest` | off | Do not publish the terminal's own position |
| `--router` | EFDI router | Zenoh mTLS router |

The package contains `app/` (the relay modules, unchanged), `certs/`, `device.env` (all settings,
including the slot read from the certificate), `bootstrap.ps1`, `run.ps1`, `install.cmd/.ps1`,
`uninstall.cmd/.ps1` and a Finnish quick-start. Register the system name **before** shipping,
or the heartbeat shows up as unknown.

**The ZIP holds the private key.** Transfer it like a secret; `dist/` is git-ignored.

## Install on the device

1. Join the mesh (`netbird up …`); the router name resolves only inside it.
2. Unzip, double-click `install.cmd`. It creates a venv, installs `eclipse-zenoh`, registers
   automatic start and starts the relay at once.
   - Automatic start tries a scheduled task (at logon, no admin). If the account may not create
     scheduled tasks, it falls back to a shortcut in the Startup folder.
   - Kiosk machines with no logged-in user: `install.ps1 -AtSystemStartup` in an admin
     PowerShell (at system start, as SYSTEM).
3. Point the terminal's CoT input at `device.env`'s `TAK_UDP_PORT` (TAK app default 6969), and
   its UDP output at `TAK_UDP_IN_PORT` if PLI is wanted.
4. Check `http://localhost:8088/status` → `"healthy": true`. Logs: `logs/relay-YYYYMMDD.log`.

To change settings: edit `device.env`, run `uninstall.cmd`, then `install.cmd`. `uninstall`
removes either start method and stops both the launcher loop and the relay.

`run.ps1 -CheckOnly` runs a preflight (Python, zenoh, certificates) without starting the relay.

The full cycle (install → healthy against the real fabric with CoT from several vendors →
uninstall → no restart) has been verified on Windows field devices.
