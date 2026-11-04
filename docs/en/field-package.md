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
| `--system` | required (not with `--template`) | Unique device name: `GATEWAY_SYSTEM`, heartbeat topic, file name |
| `--template` | off | No certificate and no device name (safe to share); `install.cmd` asks for both. This is what a [release](release.md) publishes |
| `--lang` | asked at install | `fi` or `en`: language of the installer and its messages |
| `--mode` | asked at install | `direct`, `multicast` or `server` ([modes](modes.md)) |
| `--tak-server`, `--tak-p12`, `--tak-trust-p12` | — | `server` mode: address and .p12 files (copied to `certs/tak/`). The password is asked at install |
| `--ingest-uids` | — | `TAK_INGEST_UIDS`: device uids allowed to publish |
| `--cert-dir` | `./certs` | Bundle to include (one cert/key pair + CA) |
| `--tak-host`, `--tak-udp-port` | `127.0.0.1`, `6969` | Where the TAK terminal listens for CoT |
| `--tak-port` | `8087` | TCP stream port |
| `--tak-udp-in-port` | `6971` | UDP port for PLI from the terminal |
| `--no-ingest` | off | Do not publish the terminal's own position |
| `--router` | bundle's `NOTES.md`, else EFDI router | Zenoh mTLS router |
| `--no-bundled-python` | off | Leave Python out (smaller ZIP); the device then needs Python 3.10+ and network at install |

The package contains `app/` (the relay modules, unchanged), `certs/`, `device.env` (all settings,
including the slot read from the certificate), `bootstrap.ps1`, `run.ps1`, `install.cmd/.ps1`,
`uninstall.cmd/.ps1`, `lang.ps1` (all messages in Finnish and English) and READMEs in both
languages. The scripts live in `tools/field_package/`. Register the system name **before** shipping,
or the heartbeat shows up as unknown.

**Python is included** (Windows amd64, about 25 MB in all): the embeddable Python
3.14.10 from python.org, pinned to its published SHA256, and the Windows wheels of
`eclipse-zenoh` and `cryptography` from PyPI. The device needs no Python and no network at
install. Downloads are cached in `dist/cache/`; `python/SOURCE.txt` in the ZIP lists every file
and its SHA256.

**The ZIP holds the private key.** Transfer it like a secret; `dist/` is git-ignored.

## Install on the device

1. Join the mesh (`netbird up …`); the router name resolves only inside it.
2. Unzip, double-click `install.cmd`. It asks, in this order:
   1. **Language** (Suomi / English). Everything after this, including later starts and
      uninstall, uses that language.
   2. **Mode:** direct, local network or TAK Server ([modes](modes.md)).
   3. **Details for the mode:** TAK Server address, .p12 files and password; in local-network mode
      the device uids whose position may be published.

   Anything preset with `make_relay_package.py` is not asked. The answers go to `device.env`.
   Then it registers automatic start (with `--no-bundled-python` it first creates a venv and
   installs `eclipse-zenoh`, plus `cryptography` in TAK Server mode), starts the relay and prints what to set in TAK.
   - Automatic start tries a scheduled task (at logon, no admin). If the account may not create
     scheduled tasks, it falls back to a shortcut in the Startup folder.
   - Kiosk machines with no logged-in user: `install.ps1 -AtSystemStartup` in an admin
     PowerShell (at system start, as SYSTEM).
3. Direct mode only: point the terminal's CoT input at `device.env`'s `TAK_UDP_PORT` (TAK app
   default 6969), and its UDP output at `TAK_UDP_IN_PORT` if PLI is wanted. Local-network and TAK
   Server modes need nothing in TAK.
4. Open <http://localhost:8088/>: the status page should say **Healthy**. Logs: `logs/relay-YYYYMMDD.log`.

To change settings: edit `device.env` (delete the `TAK_MODE` or `RELAY_LANG` line to be asked
again), run `uninstall.cmd`, then `install.cmd`. `device.env` may hold the TAK Server certificate
password; treat the folder like the key. `uninstall`
removes either start method and stops both the launcher loop and the relay.

`run.ps1 -CheckOnly` runs `doctor.py` (Python, zenoh, certificates, NetBird, router, ports) without
starting the relay, and prints a fix for each failure.

To publish only the device's own position, uncomment `TAK_INGEST_UIDS` in `device.env` and set
the terminal's uid.

The full cycle (install → healthy against the real fabric with CoT from several vendors →
uninstall → no restart) has been verified on Windows field devices.
