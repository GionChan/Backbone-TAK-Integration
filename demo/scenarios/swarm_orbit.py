#!/usr/bin/env python3
"""Scenario: simulated hostile drone swarm over a target area (exercise inject, not a real threat).

Flight plan (10-min cycle):
  1. INGRESS  — spawn ~40 km northeast of the target, 250 km/h
  2. ORBIT    — circle the target area at 150 km/h, different radii per drone
  3. RESET    — after RESET_SEC seconds, start over

Publishing and exercise labelling: demo/sender.py.
Env:  DRONE_COUNT  number of drones (default 4); identity/router: see relay/goat_connect.py
Run:  python demo/scenarios/swarm_orbit.py
"""

import math
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sender  # noqa: E402

_COUNT      = int(os.environ.get("DRONE_COUNT", "4"))
_TICK       = 0.5      # seconds per update
_RESET_SEC  = 600      # 10-minute cycle

_TARGET     = (60.1699, 24.9384)
_ORBIT_CTR  = (60.28,   25.05)

# deg/tick → m/s: speed_deg * 111000 / _TICK
_DEG_PER_MS  = 1.0 / 111_000         # 1 m → degrees (approx)
_INGRESS_KMH = 250.0
_ORBIT_KMH   = 150.0
_INGRESS_SPD = _INGRESS_KMH / 3.6 * _TICK * _DEG_PER_MS   # deg/tick
_ORBIT_ENTRY = 0.30    # switch to orbit when within this many degrees of the target

# spawn_lat, spawn_lon, orbit_radius_deg, orbit_dir (+1 CW / -1 CCW), alt_m
_DRONES = [
    (60.42, 25.55, 0.20,  1, 150),
    (60.55, 25.85, 0.28, -1, 200),
    (60.30, 25.70, 0.35,  1, 100),
    (60.48, 26.00, 0.23, -1, 250),
]
# angular speed so that linear speed ≈ _ORBIT_KMH
def _omega(r_deg):
    r_m = r_deg * 111_000
    return (_ORBIT_KMH / 3.6) * _TICK / r_m   # rad/tick


def _bearing(lat1, lon1, lat2, lon2) -> float:
    return (math.degrees(math.atan2(lon2 - lon1, lat2 - lat1)) + 360) % 360


def _fly(out: sender.Sender, drone_id: int) -> None:
    uid = f"hostile-uav-{drone_id:02d}"
    sp_lat, sp_lon, r_deg, orb_dir, alt = _DRONES[drone_id % len(_DRONES)]
    omega = _omega(r_deg) * orb_dir

    def new_state(seq=0):
        return {
            "phase":   "ingress",
            "lat":     sp_lat,
            "lon":     sp_lon,
            "angle":   math.pi * 2 * drone_id / _COUNT,
            "start_t": time.time(),
            "seq":     seq,
            "reset":   True,
        }

    state = new_state()
    print(f"[{uid}] spawn ({sp_lat:.2f}, {sp_lon:.2f}) ingress {_INGRESS_KMH:.0f} km/h")

    while True:
        now = time.time()
        reset_flag = state.pop("reset", False)

        if now - state["start_t"] >= _RESET_SEC:
            seq = state["seq"]
            state = new_state(seq)
            print(f"[{uid}] reset -> ingress")
            continue

        lat, lon = state["lat"], state["lon"]
        prev_lat, prev_lon = lat, lon

        if state["phase"] == "ingress":
            tlat, tlon = _TARGET
            dlat, dlon = tlat - lat, tlon - lon
            dist = math.hypot(dlat, dlon)
            if dist <= _ORBIT_ENTRY:
                state["phase"] = "orbit"
                print(f"[{uid}] entering orbit")
            else:
                step = _INGRESS_SPD / dist
                lat += dlat * step
                lon += dlon * step
        else:
            a = state["angle"] + omega
            state["angle"] = a
            lat = _ORBIT_CTR[0] + r_deg * math.sin(a)
            lon = _ORBIT_CTR[1] + r_deg * math.cos(a)

        state["lat"], state["lon"] = lat, lon

        moved = math.hypot(lat - prev_lat, lon - prev_lon)
        speed_kmh = moved * 111_000 / _TICK * 3.6
        heading   = _bearing(prev_lat, prev_lon, lat, lon)

        out.track(uid, lat, lon, alt, heading, speed_kmh, phase=state["phase"], reset=reset_flag)

        state["seq"] += 1
        time.sleep(_TICK)


def main() -> None:
    print(f"[swarm-orbit] {_COUNT} UAVs | {_INGRESS_KMH:.0f} km/h ingress | "
          f"{_ORBIT_KMH:.0f} km/h orbit | reset {_RESET_SEC}s")
    with sender.open_session("swarm-orbit") as s:
        out = sender.Sender(s, "swarm-orbit")
        for i in range(_COUNT):
            threading.Thread(target=_fly, args=(out, i), daemon=True).start()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
