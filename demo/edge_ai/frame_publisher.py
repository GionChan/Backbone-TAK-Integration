#!/usr/bin/env python3
"""Synthetic EO camera feed for demoing the edge-AI pipeline with no hardware.

Publishes  <ORG>/imagery/v1/<CAM_ID>  as JSON:
  { ts_ms, cam_id, frame_id, platform_uid,
    pose: { lat, lon, alt_agl_m, yaw_deg, gimbal_az_deg, gimbal_el_deg,
            hfov_deg, w, h },
    jpeg_b64,            # RGB JPEG, target drawn as a saturated red shape
    gt_bbox_xywh }       # ground-truth box (debug only; detector must not read it)

A UAV platform orbits a fixed area; a ground target creeps along a road; the
gimbal stays roughly slewed to the target so it sits near frame centre with
realistic wander. That gives the detector + geolocator something real to chew.
"""
from __future__ import annotations

import base64
import io
import math
import os
import time

import numpy as np
import zenoh
from PIL import Image, ImageDraw
from fabric import ORG, open_session

CAM_ID = os.environ.get("EDGE_CAM_ID", "eo-cam-01")
PLATFORM_UID = os.environ.get("EDGE_PLATFORM_UID", "EFDI.uav.recon-1")
W = int(os.environ.get("EDGE_FRAME_W", "1280"))
H = int(os.environ.get("EDGE_FRAME_H", "720"))
FPS = float(os.environ.get("EDGE_FRAME_FPS", "2"))
HFOV = float(os.environ.get("EDGE_HFOV_DEG", "62"))
ALT = float(os.environ.get("EDGE_ALT_AGL_M", "450"))
# scene anchor (target starting point); override with EDGE_TGT_LAT/LON
T_LAT0 = float(os.environ.get("EDGE_TGT_LAT", "62.2426"))
T_LON0 = float(os.environ.get("EDGE_TGT_LON", "25.7473"))
ORBIT_R_M = float(os.environ.get("EDGE_ORBIT_R_M", "900"))
R_EARTH = 6371000.0


def _dest(lat, lon, brg, dist):
    d = dist / R_EARTH
    b = math.radians(brg)
    p1, l1 = math.radians(lat), math.radians(lon)
    p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(b))
    l2 = l1 + math.atan2(math.sin(b) * math.sin(d) * math.cos(p1),
                         math.cos(d) - math.sin(p1) * math.sin(p2))
    return math.degrees(p2), math.degrees(l2)


def _bearing(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def _render(frame_id, tgt_px, tgt_py, tgt_r):
    # ground: greenish noise + a lighter "road" diagonal
    rng = np.random.default_rng(frame_id)
    base = np.zeros((H, W, 3), np.uint8)
    base[:, :, 1] = 90 + (rng.integers(0, 40, (H, W)))          # green
    base[:, :, 0] = 55 + (rng.integers(0, 30, (H, W)))
    base[:, :, 2] = 45 + (rng.integers(0, 25, (H, W)))
    img = Image.fromarray(base)
    dr = ImageDraw.Draw(img)
    dr.line([(0, H * 0.75), (W, H * 0.35)], fill=(120, 115, 100), width=26)
    # target: saturated red vehicle-ish rectangle + heading tick
    x0, y0 = tgt_px - tgt_r, tgt_py - tgt_r * 0.6
    x1, y1 = tgt_px + tgt_r, tgt_py + tgt_r * 0.6
    dr.rectangle([x0, y0, x1, y1], fill=(220, 30, 25))
    dr.line([(tgt_px, tgt_py), (tgt_px + tgt_r * 1.6, tgt_py)], fill=(235, 60, 40), width=4)
    dr.text((8, 8), f"EO {CAM_ID}  f{frame_id}", fill=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80)
    return buf.getvalue(), (x0, y0, x1 - x0, y1 - y0)


def main() -> None:
    sess, real = open_session()
    key = f"{ORG}/imagery/v1/{CAM_ID}"
    print(f"[frame-pub] {'EFDI mTLS' if real else 'LOCAL'}  PUB {key}  {W}x{H}@{FPS}fps",
          flush=True)
    dt = 1.0 / max(FPS, 0.1)
    with sess:
        pub = sess.declare_publisher(key)
        f = 0
        while True:
            t = f * dt
            # platform orbits the anchor; target crawls NE at ~4 m/s
            orbit_brg = (t * 6.0) % 360.0
            tgt_lat, tgt_lon = _dest(T_LAT0, T_LON0, 45.0, 4.0 * t)
            plat_lat, plat_lon = _dest(tgt_lat, tgt_lon, orbit_brg, ORBIT_R_M)
            yaw = _bearing(plat_lat, plat_lon, tgt_lat, tgt_lon)      # nose at target
            slant = math.hypot(ORBIT_R_M, ALT)
            gimbal_el = -math.degrees(math.atan2(ALT, ORBIT_R_M))
            # target near centre with a slow lissajous wander
            px = W / 2 + 90 * math.sin(t * 0.7) + 30 * math.sin(t * 2.3)
            py = H / 2 + 60 * math.cos(t * 0.9)
            r = max(9.0, 26.0 - slant / 400.0)
            jpg, gt = _render(f, px, py, r)
            msg = {
                "ts_ms": int(time.time() * 1000), "cam_id": CAM_ID, "frame_id": f,
                "platform_uid": PLATFORM_UID,
                "pose": {
                    "lat": round(plat_lat, 7), "lon": round(plat_lon, 7),
                    "alt_agl_m": ALT, "yaw_deg": round(yaw, 2),
                    "gimbal_az_deg": 0.0, "gimbal_el_deg": round(gimbal_el, 2),
                    "hfov_deg": HFOV, "w": W, "h": H,
                },
                "jpeg_b64": base64.b64encode(jpg).decode(),
                "gt_bbox_xywh": [round(v, 1) for v in gt],
            }
            import json
            pub.put(json.dumps(msg).encode(), encoding=zenoh.Encoding.APPLICATION_JSON)
            f += 1
            if f % 10 == 0:
                print(f"[frame-pub] {f} frames  tgt=({tgt_lat:.5f},{tgt_lon:.5f}) "
                      f"plat=({plat_lat:.5f},{plat_lon:.5f}) el={gimbal_el:.1f}", flush=True)
            time.sleep(dt)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[frame-pub] stopped", flush=True)
