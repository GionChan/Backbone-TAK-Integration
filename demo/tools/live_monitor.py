#!/usr/bin/env python3
"""Live terminal monitor — näyttää kaiken EFDI-fabricista tulevan datan."""
import json, os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "relay"))
import goat_connect as gc
import zenoh

conf, is_real = gc.make_config()
keys = (f"{gc.ORG}/exercise/**", f"{gc.KEY_PREFIX}/**")  # JSON tracks: exercise + sensor
mode = "EFDI mTLS" if is_real else "LOCAL"

print(f"\n{'='*60}")
print(f"  EFDI LIVE MONITOR — {mode}")
print(f"  Tilaus: {', '.join(keys)}")
print(f"{'='*60}\n", flush=True)

counts = {}

def on_sample(sample):
    try:
        d = json.loads(sample.payload.to_bytes())
        src   = d.get("source", str(sample.key_expr).split("/")[-1])
        lat   = d.get("lat", 0)
        lon   = d.get("lon", 0)
        alt   = d.get("alt", 0)
        spd   = d.get("speed_kmh", 0)
        hdg   = d.get("heading", 0)
        phase = d.get("phase", "?")
        dist  = d.get("dist_remaining_km", "")
        dist_str = f"  jäljellä {dist:.0f} km" if dist else ""

        counts[src] = counts.get(src, 0) + 1
        n = counts[src]

        # Värikoodi lähteen mukaan
        if "loitering" in src or "cruise" in src:
            tag = "\033[91m[UCAV]\033[0m"   # punainen
        elif "kj-" in src:
            tag = "\033[93m[KJN ]\033[0m"   # keltainen
        else:
            tag = "\033[95m[HKI ]\033[0m"   # violetti

        print(
            f"{tag} {src:<22} "
            f"lat={lat:8.4f} lon={lon:8.4f} "
            f"alt={alt:5.0f}m  {spd:5.0f}km/h  hdg={hdg:5.1f}°"
            f"  [{phase}]{dist_str}  (#{n})",
            flush=True,
        )
    except Exception as e:
        print(f"[ERR] {e}", flush=True)

with zenoh.open(conf) as s:
    subs = [s.declare_subscriber(k, on_sample) for k in keys]
    print(f"Yhdistetty. Odotetaan dataa...\n", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        total = sum(counts.values())
        print(f"\n[monitor] pysäytetty — yhteensä {total} sanomaa vastaanotettu")
        for src, n in sorted(counts.items()):
            print(f"  {src}: {n}")
