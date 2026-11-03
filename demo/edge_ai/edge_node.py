#!/usr/bin/env python3
"""EFDI edge-AI node.

Subscribes to the backbone, runs detection + geolocation, and publishes
TAK-ready CoT XML back to the backbone. The TAK relay (relay/tak_gateway.py)
turns that into map tracks.

    <ORG>/imagery/v1/**   EO frames (JSON: jpeg_b64 + pose)   --\
                                                                 >-- edge_node --> <ORG>/tak/cot/v1/<uid>   (CoT 2.0 XML)
    <ORG>/sensor/v1/**    plain telemetry cues (JSON)         --/                  <ORG>/edge/ai/v1/det/<uid> (detection record JSON)

EDGE_MODE = imagery | telemetry | both        (default: both)
See demo/edge_ai/README.md for the full env list.
"""
from __future__ import annotations

import base64
import io
import json
import os
import time
from datetime import datetime, timezone

import zenoh

from cot import build_cot, cot_type
from detector import load_detector
from fabric import ORG, open_session
from geolocate import geolocate

MODE = os.environ.get("EDGE_MODE", "both").lower()
IMAGERY_KE = os.environ.get("EDGE_IMAGERY_KE", f"{ORG}/imagery/v1/**")
SENSOR_KE = os.environ.get("EDGE_SENSOR_KE", f"{ORG}/sensor/v1/**")
COT_KE = os.environ.get("EDGE_COT_KE", f"{ORG}/tak/cot/v1")
DET_KE = os.environ.get("EDGE_DET_KE", f"{ORG}/edge/ai/v1/det")
NODE_ID = os.environ.get("EDGE_NODE_ID", "edge-ai-01")
MIN_CONF = float(os.environ.get("EDGE_CONF", "0.35"))
TELEM_HZ = float(os.environ.get("EDGE_TELEM_MAX_HZ", "1.0"))  # throttle per source

_STATS = {"frames": 0, "cues": 0, "cot": 0, "skip": 0}
_last_emit: dict[str, float] = {}


def _now_ms() -> int:
    return int(time.time() * 1000)


def _publish_cot(sess, uid, xml, det_record):
    sess.put(f"{COT_KE}/{uid}", xml.encode(), encoding=zenoh.Encoding.APPLICATION_XML)
    sess.put(
        f"{DET_KE}/{uid}",
        json.dumps(det_record).encode(),
        encoding=zenoh.Encoding.APPLICATION_JSON,
    )
    _STATS["cot"] += 1
    if _STATS["cot"] % 10 == 0:
        print(f"[edge-ai] emitted {_STATS['cot']} CoT  last={uid}", flush=True)


# ---------------------------------------------------------------- imagery path
def _decode_frame(payload: bytes):
    import numpy as np
    from PIL import Image

    msg = json.loads(payload)
    jpg = base64.b64decode(msg["jpeg_b64"])
    img = Image.open(io.BytesIO(jpg)).convert("RGB")
    return msg, np.asarray(img)


def _on_frame(sess, detector, sample):
    try:
        msg, rgb = _decode_frame(sample.payload.to_bytes())
    except Exception as e:  # noqa: BLE001
        print(f"[edge-ai] frame decode error: {e}", flush=True)
        return
    _STATS["frames"] += 1
    pose = msg.get("pose", {})
    cam = msg.get("cam_id", str(sample.key_expr).split("/")[-1])
    H, W = rgb.shape[:2]
    for i, det in enumerate(detector.detect(rgb)):
        if det.conf < MIN_CONF:
            _STATS["skip"] += 1
            continue
        geo = geolocate(pose, det.cx, det.cy, image_wh=(W, H))
        # stable per (camera, detection-slot) so the marker moves instead of
        # leaving a breadcrumb trail; a real tracker would assign track ids here.
        uid = f"EDGEAI.{NODE_ID}.{cam}.d{i}"
        xml = build_cot(
            uid=uid, label=det.label, conf=det.conf,
            lat=geo["lat"], lon=geo["lon"], hae=float(pose.get("target_hae_m", 0.0)),
            course=pose.get("target_course_deg"), ce_m=geo["ce_m"],
            parent_uid=msg.get("platform_uid") or f"EFDI.{cam}",
            parent_type="a-f-A-M-F-Q", node_id=NODE_ID, model=detector.name,
            sensor={
                "azimuth": geo["bearing_deg"], "range": geo["ground_range_m"],
                "fov": pose.get("hfov_deg"), "type": "EO",
            },
            remarks_extra=f"| src={cam} bbox={[round(v) for v in det.bbox]} "
                          f"geo={geo['method']}",
        )
        rec = {
            "uid": uid, "ts_ms": _now_ms(), "node": NODE_ID, "model": detector.name,
            "cam_id": cam, "frame_id": msg.get("frame_id"),
            "label": det.label, "conf": det.conf,
            "bbox_xywh": [round(v, 1) for v in det.bbox], "image_wh": [W, H],
            "pose": pose, "geo": geo, "cot_type": cot_type(det.label),
            "src_key": str(sample.key_expr),
        }
        _publish_cot(sess, uid, xml, rec)


# --------------------------------------------------------------- telemetry path
def _classify_cue(d: dict) -> tuple[str, float]:
    """Rule-based 'classifier' over a plain telemetry sample -> (label, conf)."""
    t = str(d.get("type", "")).lower()
    spd = float(d.get("speed_kmh", 0) or 0)
    alt = float(d.get("alt", d.get("alt_m", 0)) or 0)
    if "uav" in t or "drone" in t or (50 < spd < 600 and 30 < alt < 8000):
        conf = 0.6 + min(0.35, spd / 2000 + alt / 40000)
        return "uav", round(min(conf, 0.97), 3)
    if "vehicle" in t or "convoy" in t or spd < 140:
        return "vehicle", 0.55
    return d.get("type", "unknown") or "unknown", 0.5


def _on_cue(sess, sample):
    now = time.time()
    src = str(sample.key_expr)
    if now - _last_emit.get(src, 0) < 1.0 / max(TELEM_HZ, 0.01):
        return
    try:
        d = json.loads(sample.payload.to_bytes())
        lat, lon = float(d["lat"]), float(d["lon"])
    except Exception:  # noqa: BLE001
        return
    _last_emit[src] = now
    _STATS["cues"] += 1
    label, conf = _classify_cue(d)
    if conf < MIN_CONF:
        _STATS["skip"] += 1
        return
    name = d.get("source") or src.split("/")[-1]
    uid = f"EDGEAI.{NODE_ID}.{name}"
    spd_ms = (float(d.get("speed_kmh", 0) or 0)) / 3.6 or None
    xml = build_cot(
        uid=uid, label=label, conf=conf, lat=lat, lon=lon,
        hae=float(d.get("alt", d.get("alt_m", 0)) or 0.0),
        course=d.get("heading", d.get("heading_deg")), speed_ms=spd_ms,
        ce_m=float(d.get("ce_m", 25.0)), parent_uid=f"EFDI.{name}",
        parent_type="a-f-A-M-F-Q", node_id=NODE_ID, model="cue-classifier/1",
        remarks_extra=f"| cue={src.split('/')[-1]}",
    )
    rec = {
        "uid": uid, "ts_ms": _now_ms(), "node": NODE_ID, "model": "cue-classifier/1",
        "label": label, "conf": conf, "lat": lat, "lon": lon,
        "cot_type": cot_type(label), "src_key": src, "cue": d,
    }
    _publish_cot(sess, uid, xml, rec)


# ----------------------------------------------------------------------- main
def main() -> None:
    detector = load_detector() if MODE in ("imagery", "both") else None
    sess, real = open_session()
    tag = "EFDI mTLS backbone" if real else "LOCAL fallback"
    print(f"[edge-ai] node={NODE_ID} mode={MODE} via {tag}", flush=True)
    print(f"[edge-ai] detector={getattr(detector, 'name', 'none')} "
          f"min_conf={MIN_CONF}", flush=True)
    subs = []
    with sess:
        if real and os.environ.get("EDGE_HEARTBEAT", "1") == "1":
            import heartbeat  # relay/heartbeat.py (on sys.path via fabric.py; copied into the image)

            def _healthy() -> bool:
                return bool(list(sess.info.routers_zid()))

            heartbeat.Heartbeat(
                sess, ORG, os.environ.get("EDGE_SYSTEM", "edge-ai"), version="1.0.0",
                interval=float(os.environ.get("GOAT_HEARTBEAT_INTERVAL_S", "60")),
                health_fn=_healthy, log=lambda m: print(f"[edge-ai] {m}", flush=True)).start()
        if MODE in ("imagery", "both"):
            subs.append(sess.declare_subscriber(
                IMAGERY_KE, lambda s: _on_frame(sess, detector, s)))
            print(f"[edge-ai] SUB imagery  {IMAGERY_KE}", flush=True)
        if MODE in ("telemetry", "both"):
            subs.append(sess.declare_subscriber(
                SENSOR_KE, lambda s: _on_cue(sess, s)))
            print(f"[edge-ai] SUB telemetry {SENSOR_KE}", flush=True)
        print(f"[edge-ai] PUB cot     {COT_KE}/<uid>", flush=True)
        print("[edge-ai] ready - Ctrl-C to stop", flush=True)
        try:
            while True:
                time.sleep(15)
                print(f"[edge-ai] stats {datetime.now(timezone.utc):%H:%M:%S} "
                      f"{_STATS}", flush=True)
        except KeyboardInterrupt:
            pass
    print(f"[edge-ai] stopped {_STATS}", flush=True)


if __name__ == "__main__":
    main()
