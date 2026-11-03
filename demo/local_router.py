#!/usr/bin/env python3
"""Minimal local Zenoh router for development without EFDI mesh."""
import time
import zenoh

conf = zenoh.Config()
conf.insert_json5("mode", '"router"')
conf.insert_json5("listen/endpoints", '["tcp/0.0.0.0:7447"]')
conf.insert_json5("scouting/multicast/enabled", "false")

print("[router] starting on tcp/0.0.0.0:7447", flush=True)
with zenoh.open(conf) as _s:
    print("[router] ready", flush=True)
    try:
        while True:
            time.sleep(5)
    except KeyboardInterrupt:
        pass
