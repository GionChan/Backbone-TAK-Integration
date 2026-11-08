# Field-device package (Windows and Linux, no Docker)

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
| `--ingest-uids` | — | `TAK_INGEST_UIDS`: device uids allowed to publish (`*` = any) |
| `--share-markers` | asked at install | `on` or `off`: `TAK_SHARE_MARKERS`, markers and drawings to the backbone |
| `--cert-dir` | `./certs` | Bundle to include (one cert/key pair + CA) |
| `--tak-host`, `--tak-udp-port` | `127.0.0.1`, `6969` | Where the TAK terminal listens for CoT |
| `--tak-port` | `8087` | TCP stream port |
| `--tak-udp-in-port` | `6971` | UDP port for PLI from the terminal |
| `--no-ingest` | off | Do not publish the terminal's own position |
| `--router` | bundle's `NOTES.md` (required without it) | Zenoh mTLS router |
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
   4. **Sharing markers and drawings:** off, or on (every CoT marker and drawing, hostile ones
      too, goes to the backbone; messages never).

   Anything preset with `make_relay_package.py` is not asked. The answers go to `device.env`.
   Then it registers automatic start (with `--no-bundled-python` it first creates a venv and
   installs `eclipse-zenoh`, plus `cryptography` in TAK Server mode), starts the relay and prints what to set in TAK.
   - Automatic start tries a scheduled task (at logon, no admin). If the account may not create
     scheduled tasks, it falls back to a shortcut in the Startup folder.
   - Kiosk machines with no logged-in user: `install.ps1 -AtSystemStartup` in an admin
     PowerShell (at system start, as SYSTEM).
   - The installer limits the folder to the installing user, SYSTEM and Administrators, so other
     users of the machine can neither read the key nor change the scripts SYSTEM runs.
3. Direct mode only: point the terminal's CoT input at `device.env`'s `TAK_UDP_PORT` (default
   6969), and its UDP output at `TAK_UDP_IN_PORT` if PLI is wanted. Local-network and TAK
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

## Linux

Build the package with `--platform linux`:

```bash
python tools/make_relay_package.py --system field-relay-02 --platform linux   # → dist/field-relay-02-tak-relay-linux.tar.gz
```

The `.tar.gz` holds one folder with `app/`, `certs/`, `device.env`, `install.sh`, `run.sh`,
`uninstall.sh`, `common.sh`, `lang.txt` (all messages in Finnish and English), READMEs in both
languages and the dependency wheels for x86_64 and aarch64 (Python 3.10–3.14, about 50 MB). The
options are those of the Windows package; `--no-bundled-wheels` leaves the wheels out, and the
device then needs network at install. The scripts live in `tools/field_package/linux/`.

The device needs glibc 2.28 or newer (e.g. Debian 12+, Ubuntu 22.04+, 64-bit Raspberry Pi OS 12+),
Python 3.10+ with the venv module (`sudo apt install python3 python3-venv`) and bash. Musl-based
systems such as Alpine are not supported.

Install as the user who will run the relay, not as root:

```bash
tar -xzf field-relay-02-tak-relay-linux.tar.gz && cd field-relay-02-tak-relay-linux
./install.sh             # systemd user service: starts when you sign in
./install.sh --at-boot   # systemd service that starts with the machine; sudo only to install it
```

The installer asks what the Windows installer asks. In direct mode it also asks where CoT goes by
UDP (`TAK_UDP_TARGETS`) and which other devices may publish their own position
(`TAK_INGEST_UIDS`): on Linux the TAK apps are usually on other devices, and without the list only
TAK apps on this machine are published.

- The `--at-boot` service runs as the installing user, never as root.
- The user service starts with the machine when the installer can enable lingering
  (`loginctl enable-linger`); otherwise it says so, and `--at-boot` is the way for a device nobody
  signs in to.
- Without a systemd user session the installer adds an `@reboot` line to the user's crontab.
- Installing again replaces the earlier start method, so only one relay starts for the folder.
- Logs are written per day and kept 14 days.
- The package folder and `certs/` are made 700, the key, the .p12 files and `device.env` 600.
- `./run.sh --check-only` runs `doctor.py`; logs are in `logs/`; `./uninstall.sh` removes the
  automatic start and stops the relay.
- A firewall (e.g. ufw) must let TAK devices reach TCP 8087 and UDP 6971 (direct) or the multicast
  group (local network). Local-network mode works natively on Linux, unlike Docker Desktop.

CI installs, checks and uninstalls the Linux package on Ubuntu for every push and pull request to
`main` and before every release. It has not yet been tried on a field device with real TAK devices.
