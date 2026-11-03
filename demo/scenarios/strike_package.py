#!/usr/bin/env python3
"""Scenario: 10-UAV strike package start area -> target (exercise inject, not a real threat).

Different speeds, altitudes, types and start offsets. Positions are published through
demo/sender.py (exercise-labelled JSON + CoT); the TAK relay brings them to TAK clients.
Run:  python demo/scenarios/strike_package.py
"""
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sender  # noqa: E402

# ── Geographic constants ──────────────────────────────────────────────────────
START     =(64.2255, 27.7357)
TARGET    =(62.2415, 25.7209)

def _bearing(lat1, lon1, lat2, lon2):
    """Great-circle initial bearing in degrees (0=N, 90=E)."""
    φ1, φ2 = math.radians(lat1), math.radians(lat2)
    Δλ = math.radians(lon2 - lon1)
    x = math.sin(Δλ) * math.cos(φ2)
    y = math.cos(φ1) * math.sin(φ2) - math.sin(φ1) * math.cos(φ2) * math.cos(Δλ)
    return (math.degrees(math.atan2(x, y)) + 360) % 360

def _move(lat, lon, bearing_deg, dist_km):
    """Move point by dist_km along bearing, return (lat, lon)."""
    R = 6371.0
    d = dist_km / R
    φ1 = math.radians(lat)
    λ1 = math.radians(lon)
    b  = math.radians(bearing_deg)
    φ2 = math.asin(math.sin(φ1)*math.cos(d) + math.cos(φ1)*math.sin(d)*math.cos(b))
    λ2 = λ1 + math.atan2(math.sin(b)*math.sin(d)*math.cos(φ1),
                          math.cos(d) - math.sin(φ1)*math.sin(φ2))
    return math.degrees(φ2), math.degrees(λ2)

def _dist_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    φ1, φ2 = math.radians(lat1), math.radians(lat2)
    Δφ = math.radians(lat2 - lat1)
    Δλ = math.radians(lon2 - lon1)
    a = math.sin(Δφ/2)**2 + math.cos(φ1)*math.cos(φ2)*math.sin(Δλ/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

# ── UAV fleet ─────────────────────────────────────────────────────────────────
# (name, speed_kmh, alt_m, lat_offset, lon_offset, cot_type)
FLEET = [
    ("kj-shadow-01", 280, 1500,  0.00,  0.00, "a-h-A-M-F-Q"),   # lead
    ("kj-shadow-02", 320, 2000,  0.15,  0.10, "a-h-A-M-F-Q"),   # high fast
    ("kj-shadow-03", 240, 800,  -0.10,  0.20, "a-h-A-M-F-Q"),   # slow low
    ("kj-shadow-04", 350, 3000,  0.25, -0.10, "a-h-A-M-F-Q"),   # high speed
    ("kj-loitering-05", 180, 300, -0.20,  0.30, "a-h-A-M-F"),   # UCAV loiter
    ("kj-loitering-06", 200, 250,  0.30,  0.25, "a-h-A-M-F"),   # UCAV loiter
    ("kj-shadow-07", 300, 1200,  0.10, -0.20, "a-h-A-M-F-Q"),   # mid
    ("kj-shadow-08", 260, 600,  -0.30, -0.15, "a-h-A-M-F-Q"),   # low
    ("kj-cruise-09", 220, 100,   0.20,  0.35, "a-h-A-M-F-Q"),   # terrain-hug
    ("kj-cruise-10", 230, 150,  -0.15, -0.30, "a-h-A-M-F-Q"),   # terrain-hug
]

TARGET_LAT, TARGET_LON = TARGET

# ── Main loop ─────────────────────────────────────────────────────────────────
def main():
    total_dist = _dist_km(*START, *TARGET)
    base_bearing = _bearing(*START, *TARGET)
    print(f"[strike-package] route: {total_dist:.0f} km  bearing={base_bearing:.1f}°", flush=True)

    with sender.open_session("strike-package") as s:
        out = sender.Sender(s, "strike-package")
        tick = 0
        while True:
            t = tick * 0.5  # seconds elapsed

            for name, speed_kmh, alt_m, lat_off, lon_off, cot_type in FLEET:
                dist_traveled = speed_kmh * (t / 3600.0)

                # Start point = START + individual offset
                start_lat = START[0] + lat_off
                start_lon = START[1] + lon_off

                # Bearing toward the target from this UAV's start
                bearing = _bearing(start_lat, start_lon, TARGET_LAT, TARGET_LON)
                total_leg = _dist_km(start_lat, start_lon, TARGET_LAT, TARGET_LON)

                if dist_traveled >= total_leg:
                    # Reset: loop back to start
                    lat, lon = start_lat, start_lon
                else:
                    lat, lon = _move(start_lat, start_lon, bearing, dist_traveled)

                remaining_km = _dist_km(lat, lon, TARGET_LAT, TARGET_LON)

                out.track(name, lat, lon, alt_m, bearing, speed_kmh, phase="ingress",
                          cot_type=cot_type, target="objective",
                          dist_remaining_km=round(remaining_km, 1))

            tick += 1
            if tick % 20 == 0:
                sample = FLEET[0]
                dist_t = sample[1] * (tick * 0.5 / 3600)
                print(
                    f"[strike-package] tick={tick}  lead dist_traveled={dist_t:.1f} km",
                    flush=True,
                )

            time.sleep(0.5)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[strike-package] stopped", flush=True)
