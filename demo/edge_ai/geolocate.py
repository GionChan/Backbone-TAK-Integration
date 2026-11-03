"""Turn a detection pixel box + platform/gimbal pose into a ground lat/lon.

Model: pinhole camera + flat local ground plane at the platform's ground
elevation. Good to a few tens of metres for small depression angles and low
altitudes; swap in a DEM ray-cast for production. Everything is plain trig, no
deps beyond math.

pose dict (all optional, sensible fallbacks):
  lat, lon                target-agnostic platform position (deg)          [required]
  alt_agl_m               height above the ground plane (m)                [default 120]
  yaw_deg                 platform/camera boresight azimuth, 0=N cw        [default 0]
  gimbal_az_deg           extra azimuth offset of the gimbal vs boresight  [default 0]
  gimbal_el_deg           gimbal elevation, negative = looking down        [default -30]
  hfov_deg               horizontal field of view                         [default 62]
  w, h                    image size in px (else taken from image_wh arg)
"""
from __future__ import annotations

import math

_R_EARTH = 6371000.0


def _dest(lat, lon, bearing_deg, dist_m):
    d = dist_m / _R_EARTH
    br = math.radians(bearing_deg)
    p1 = math.radians(lat)
    l1 = math.radians(lon)
    p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(br))
    l2 = l1 + math.atan2(
        math.sin(br) * math.sin(d) * math.cos(p1),
        math.cos(d) - math.sin(p1) * math.sin(p2),
    )
    return math.degrees(p2), (math.degrees(l2) + 540) % 360 - 180


def geolocate(pose: dict, cx: float, cy: float, image_wh: tuple[int, int] | None = None):
    """Return dict: lat, lon, method, ground_range_m, bearing_deg, ce_m."""
    lat = float(pose["lat"])
    lon = float(pose["lon"])
    h = float(pose.get("alt_agl_m", 120.0))
    yaw = float(pose.get("yaw_deg", 0.0)) + float(pose.get("gimbal_az_deg", 0.0))
    el = float(pose.get("gimbal_el_deg", -30.0))
    hfov = float(pose.get("hfov_deg", 62.0))
    W = float(pose.get("w") or (image_wh or (1280, 720))[0])
    Hpx = float(pose.get("h") or (image_wh or (1280, 720))[1])
    vfov = math.degrees(2 * math.atan(math.tan(math.radians(hfov) / 2) * (Hpx / W)))

    # pixel -> angular offset from boresight (right +, up +)
    ax = (cx / W - 0.5) * hfov
    ay = (0.5 - cy / Hpx) * vfov

    depression = -(el + ay)  # degrees below horizontal along the target ray
    bearing = (yaw + ax) % 360.0

    if h <= 0 or depression <= 0.15:
        # ray never meets the ground (looking at/above horizon) -> best effort:
        # report the platform's own nadir point.
        return {
            "lat": round(lat, 7), "lon": round(lon, 7), "method": "platform-nadir",
            "ground_range_m": 0.0, "bearing_deg": round(bearing, 1), "ce_m": 75.0,
        }

    grange = h / math.tan(math.radians(depression))
    tlat, tlon = _dest(lat, lon, bearing, grange)
    # crude error budget: grows with range and shallow look angle
    ce = max(8.0, 0.06 * grange + 3.0 / math.tan(math.radians(max(depression, 1.0))))
    return {
        "lat": round(tlat, 7), "lon": round(tlon, 7), "method": "pinhole-flat-ground",
        "ground_range_m": round(grange, 1), "bearing_deg": round(bearing, 1),
        "ce_m": round(ce, 1),
    }
