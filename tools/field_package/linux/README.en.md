# EFDI TAK relay: {system} (Linux)

**Suomeksi:** README.fi.md

This package connects the device to the EFDI backbone and brings the backbone picture to TAK
devices. The dependencies for x86_64 and aarch64 are included, so installing needs no network.
The installer makes the relay start automatically.

Needs: a Linux with glibc 2.28 or newer (e.g. Debian 12+, Ubuntu 22.04+, 64-bit Raspberry Pi OS 12+),
Python 3.10 or newer with the venv module (`sudo apt install python3 python3-venv`), bash.

## Before installing

1. Join the device to the EFDI NetBird network (`netbird status` → Management and Signal: Connected).
2. The system name `{system}` must be registered in the EFDI portal. Otherwise the heartbeat shows
   up as unknown; data still flows.
3. If you choose TAK Server mode, ask the TAK Server administrator for a client certificate
   (.p12) and a truststore (.p12) for the relay, and copy them to `certs/tak/`.

## Installing

Unpack and run the installer as the user who will run the relay (not as root):

```bash
tar -xzf <package>.tar.gz && cd <folder>
./install.sh             # starts when you sign in (systemd user service)
./install.sh --at-boot   # starts with the machine; asks for sudo only to install the service
```

If this is the template from a release, the installer first asks for your EFDI certificate
bundle (folder, `.zip` or `.tar.gz`) and the device name. Then it asks for:

1. **Language:** Finnish or English.
2. **Mode:**

| Mode | For | What to set in TAK | Who sees the picture |
| --- | --- | --- | --- |
| 1 Direct | Named devices (UDP) and ATAK/WinTAK over TCP {tak_port} | The relay's address | Only those devices |
| 2 Local network | A closed network of your own | Nothing | Everyone on the network |
| 3 TAK Server | An organisation with a TAK Server | Nothing | Every user on the server |

3. **Details for the mode:** in direct mode where CoT goes by UDP and which other devices may
   publish their own position; in TAK Server mode the server address, certificates and password;
   in local-network mode the devices whose own position may be published.
4. **Sharing markers and drawings:** off, or on (every CoT marker and drawing, hostile ones
   too, goes to the backbone; messages never).

Without a list of device uids only TAK apps on this machine may publish their position to the
backbone. TAK Server users are never published.

The installer makes the certificates and `device.env` readable by this user only. Without
systemd it adds an `@reboot` line to your crontab instead.

## While running

- **Status page:** <http://127.0.0.1:8088/> (this machine only).
- **Troubleshooting:** `./run.sh --check-only` checks certificates, NetBird, connections and ports
  and prints a fix for each failure.
- **Logs:** `logs/relay-YYYYMMDD.log`.
- **Firewall:** TAK devices on the network must reach TCP {tak_port} and UDP 6971 (direct) or the
  multicast group (local network).

## Changing settings

Edit `device.env`, or delete its `TAK_MODE` and `RELAY_LANG` lines so the installer asks again.
Then run `./uninstall.sh` and `./install.sh`.

## Uninstalling

`./uninstall.sh` removes the automatic start and stops the relay. The folder stays in place.

## Security

`certs/` holds your organisation's private key, and `device.env` may hold the TAK Server
certificate password. Do not pass the package or the folder on.
