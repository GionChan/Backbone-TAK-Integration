#!/usr/bin/env python3
"""Verify EFDI mTLS connection using certs from /certs."""
import json, time, sys, os
import zenoh
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "relay"))
import goat_connect as gc

print(f"router : {gc.ROUTER}", flush=True)
print(f"prefix : {gc.KEY_PREFIX}", flush=True)

conf, is_real = gc.make_config()
print(f"mode   : {'EFDI mTLS' if is_real else 'LOCAL fallback'}", flush=True)

if not is_real:
    print("ERROR: no certs found, cannot test EFDI", flush=True)
    sys.exit(1)

received = []

def on_sample(sample):
    try:
        d = json.loads(sample.payload.to_bytes())
        received.append(d)
        print(f"RX: {sample.key_expr}  src={d.get('source')}  lat={d.get('lat'):.4f}", flush=True)
    except Exception as e:
        print(f"RX error: {e}", flush=True)

print("opening zenoh session...", flush=True)
with zenoh.open(conf) as s:
    sub = s.declare_subscriber(f"{gc.KEY_PREFIX}/**", on_sample)
    print(f"subscribed to {gc.KEY_PREFIX}/**  — waiting 6s", flush=True)
    time.sleep(6)
    print(f"total received: {len(received)}", flush=True)
