# Overview

**Suomeksi:** [../fi/overview.md](../fi/overview.md)

## The problem

EFDI partners share sensor data over the **goat fabric**: a data network where each organisation
publishes under its own namespace and reads what others publish. Users look at the situation in
**TAK** applications (WinTAK, ATAK and other CoT clients), which speak a different language,
Cursor on Target (CoT). Something has to sit between the two, translate, and keep bad data out.
That is the TAK relay.

## How data travels

Think of the fabric as a post office with labelled mailboxes. A sender drops a letter into
`<org>/sensor/v1/uav-1`; anyone allowed to read that box gets a copy. The relay subscribes to
the boxes it cares about, rewrites each letter in CoT and hands it to the TAK clients.

```text
 Other vendors          Your sensors          Demo scenarios (exercise-labelled)
      │                      │                          │
      └──────── EFDI goat fabric (Zenoh, mTLS, NetBird WireGuard mesh) ────────┘
                                   │
                         ┌─────────▼──────────┐
                         │     TAK relay      │  relay/tak_gateway.py
                         │ convert → validate │
                         │ → rate-limit → fan │
                         └──┬──────┬───────┬──┘
                 UDP 6969/4242   TCP 8087   RTSP 8554 (video)
                    UDP clients   ATAK        TAK "Play Video"
                    WinTAK        WinTAK
```

Four layers make the path secure:

1. **NetBird / WireGuard** builds an encrypted mesh between the participants' machines. Without
   it the fabric's router is not even reachable.
2. **mTLS** — both ends show a certificate. Your certificate's name is your **slot** (a 32-hex
   id); the fabric lets you write only under `<slot>/**`. Writes elsewhere are dropped silently.
3. **Zenoh** carries the messages (publish/subscribe on key expressions such as
   `*/tak/cot/v1/**`).
4. **CoT** is what TAK understands: an XML `<event>` with a position, a type (friend, hostile,
   air, ground…), and a time after which the marker goes stale.

## What the relay does with a message

1. **Recognise** the format: CoT XML, `goat.geo.track.v1`, MAVLink, ADS-B, protobuf tracks,
   vendor-specific track formats ([full list](relay.md#recognised-formats)) or your own JSON
   telemetry. Unknown formats are counted and skipped.
2. **Convert** it to CoT, inferring the symbol (affiliation and dimension) when the source does
   not state it.
3. **Validate**: well-formed XML, no DTD, coordinates in range, not already stale, under 64 KiB.
   Other vendors' CoT is forwarded byte-for-byte only after this check.
4. **Rate-limit** per track and drop duplicates that arrive over several keys.
5. **Fan out** to every output. A slow TAK client only loses its own frames; it cannot stall the
   others.

In the other direction (optional), friendly positions from your own TAK users are published to
`<slot>/tak/pli/v1/<uid>`, and the markers and drawings they make to `<slot>/tak/cot/v1/<uid>`,
so other participants see them. Messages are never published.

## Product and demo

The repository holds two things that are kept apart:

- **The relay** (`relay/`) is what you deploy. It reads real backbone data.
- **The demo** (`demo/`) shows the relay working. Scenarios compute flight paths; the **demo
  sender** (`demo/sender.py`) publishes them to `<slot>/exercise/<scenario>/v1/<uid>` and a CoT
  marker to `<slot>/tak/cot/v1/EXERCISE.<uid>`. Every demo message says
  `"classification": "SIMULATED"`, every marker's callsign starts with `EXERCISE`. Demo data
  never goes to `<slot>/sensor/v1/**`, where real telemetry lives.

The demo deliberately uses the same path as real data: its markers reach TAK through the relay,
not through a side channel.

## Words used in these documents

| Term | Meaning |
| --- | --- |
| Fabric, backbone | The EFDI goat data network (Zenoh routers reachable over the mesh) |
| Slot, org | Your identity on the fabric: the certificate CN, also your write namespace |
| Bundle | The onboarding files: `<prefix>-cert.pem`, `<prefix>-key.pem`, `efdi-ca-root.pem` |
| CoT | Cursor on Target, the XML event format TAK uses |
| PLI | Position location information: a TAK user's own position |
| Heartbeat | The mandatory `<slot>/<system>/heartbeat/v1` message every 60 s |
| Stale | The time after which TAK removes a marker that has not been updated |
