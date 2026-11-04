# EFDI TAK relay: {system}

**Suomeksi:** README.fi.md

This package connects the device to the EFDI backbone and brings the backbone picture into TAK
apps. Python and everything else the relay needs are included, so installing needs no network.
The installer makes the relay start automatically.

## Before installing

1. Join the device to the EFDI NetBird network (`netbird status` → Management and Signal: Connected).
2. The system name `{system}` must be registered in the EFDI portal. Otherwise the heartbeat shows
   up as unknown; data still flows.
3. If you choose TAK Server mode, ask the TAK Server administrator for a client certificate
   (.p12) and a truststore (.p12) for the relay, and copy them to `certs\tak\`.

## Installing

If this is the template from a release, the installer first asks for your EFDI certificate
bundle (folder, `.zip` or `.tar.gz`) and the device name.

Unzip anywhere and double-click `install.cmd`. If Windows warns ("Windows protected your PC"),
choose "More info" → "Run anyway".

The installer asks for:

1. **Language:** Finnish or English.
2. **Mode:**

| Mode | For | What to set in TAK | Who sees the picture |
| --- | --- | --- | --- |
| 1 Direct | This machine or a few named devices | One input port (UDP {tak_udp_port} or TCP {tak_port}) | Only those devices |
| 2 Local network | A closed network of your own | Nothing | Everyone on the network |
| 3 TAK Server | An organisation with a TAK Server | Nothing | Every user on the server |

3. **Details for the mode:** in TAK Server mode the server address, certificates and password.
   In local-network mode the devices whose own position may be published to the backbone.

Finally the installer starts the relay, checks its status and tells you what to set in the TAK
app. The choices are saved in `device.env`.

For a device nobody signs in to (kiosk or server): `install.cmd -AtSystemStartup` as
administrator. The relay then starts with the machine.

## While running

- **Status page:** <http://127.0.0.1:8088/> shows whether the relay is healthy and, if not, why.
- **Troubleshooting:** `.\run.ps1 -CheckOnly` checks certificates, NetBird, connections and ports
  and prints a fix for each failure.
- **Logs:** `logs\relay-YYYYMMDD.log`.

## Changing settings

Edit `device.env`, or delete its `TAK_MODE` and `RELAY_LANG` lines so the installer asks again.
Then run `uninstall.cmd` and `install.cmd`.

Only your own devices' positions are published to the backbone, and only with `TAK_INGEST=1`.
Other users on a TAK Server are never published.

## Uninstalling

`uninstall.cmd` removes the automatic start and stops the relay. The folder stays in place.

## Security

`certs\` holds your organisation's private key, and `device.env` may hold the TAK Server
certificate password. Do not pass the package or the folder on.
