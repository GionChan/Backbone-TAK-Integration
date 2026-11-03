# EFDI edge-AI demo

> **Demo component.** Mock detector and synthetic camera by default. Its CoT is not
> exercise-labelled like `demo/sender.py` output: set `EDGE_COT_AFFIL=u` before running it on a
> shared fabric so the markers are not shown as confirmed hostiles.

An edge-compute node that **subscribes raw data from the backbone, processes it,
and publishes TAK-ready CoT markers back to the backbone** — so a detection made
at the edge shows up on WinTAK/ATAK straight from the fabric, with no app-side
processing.

```
                       EFDI Zenoh backbone  (mTLS, router.example:7447)
  frame_publisher ─▶ <ORG>/imagery/v1/<cam>  ─┐
   (synthetic EO)                             │  ┌──────────── edge_node.py ─────────────┐
                                              ├─▶│ decode JPEG → detector → geolocate →  │─▶ <ORG>/tak/cot/v1/<uid>   (CoT 2.0 XML)
  live sensors ────▶ <ORG>/sensor/v1/**  ─────┘  │ cue-classifier (telemetry mode)       │─▶ <ORG>/edge/ai/v1/det/<uid> (detection JSON, audit)
                                                 └──────────────────────────────────────┘
                                                                                          │
  partner box ⇄ HTTP  ─▶ api_gateway.py  ⇄ backbone   (GET /intake/frames SSE, POST /detections/cot)
                                                                                          ▼
                                                     TAK relay (relay/tak_gateway.py) ─ CoT → WinTAK / ATAK
```

The relay picks up `<ORG>/tak/cot/v1/**` like any other vendor's CoT, validates it and sends it
to the TAK clients. Everything here runs as a container or on a separate edge box.

## Key spaces / schemas  (EFDI schema-declaration discipline)

| Key | Encoding | Payload |
| --- | --- | --- |
| `<ORG>/imagery/v1/<cam-id>` | `application/json` | `{ts_ms, cam_id, frame_id, platform_uid, pose{lat,lon,alt_agl_m,yaw_deg,gimbal_az_deg,gimbal_el_deg,hfov_deg,w,h}, jpeg_b64, gt_bbox_xywh?}` |
| `<ORG>/sensor/v1/<id>` | `application/json` | existing telemetry (`{source,lat,lon,alt,heading,speed_kmh,type,...}`) — consumed as a detection *cue* in telemetry mode |
| `<ORG>/tak/cot/v1/<uid>` | `application/xml` | CoT 2.0 `<event>` — **the TAK-ready marker**, forwarded verbatim to ATAK/WinTAK |
| `<ORG>/edge/ai/v1/det/<uid>` | `application/json` | structured detection record: `{uid,ts_ms,node,model,cam_id,frame_id,label,conf,bbox_xywh,image_wh,pose,geo,cot_type,src_key}` — provenance/audit sidecar for every marker |

UID scheme: `EDGEAI.<node-id>.<cam-or-source>[.d<slot>]`. Stable per track so the
marker moves instead of leaving a breadcrumb trail. CoT carries a
`<link relation="p-p">` back to the parent sensor/platform and a
`<_flow-tags_ efdi-edge-ai="...">` provenance stamp.

## Components

| File | Role |
| --- | --- |
| `edge_node.py` | main loop; `EDGE_MODE=imagery\|telemetry\|both` |
| `detector.py` | `Detection` + `load_detector()`. `mock` = real red-blob CV (no model, air-gap OK); `onnx` = YOLOv5/8 ONNX via onnxruntime |
| `geolocate.py` | pixel bbox + platform/gimbal pose → ground lat/lon (pinhole + flat local ground plane); returns `ce_m` error estimate |
| `cot.py` | `build_cot(...)` → CoT 2.0 XML; `cot_type(label, affil)` label→2525-ish type map |
| `fabric.py` | mTLS `zenoh.open()`; bundle and org slot via `relay/identity.py` (copied into the image) |
| `frame_publisher.py` | synthetic EO feed (orbiting UAV, crawling ground target) so the imagery path demos with zero hardware |
| `api_gateway.py` | HTTP↔backbone bridge for non-Zenoh AI boxes |
| `Dockerfile` | `python:3.12-slim` + `eclipse-zenoh`, `numpy`, `pillow` |

## Run

```powershell
.\demo\run-backbone-demo.ps1 -EdgeAI              # relay + demo stack + edge-ai + frame-pub

docker compose --profile edge up -d --build       # edge-ai + frame-pub only
docker compose --profile edge-api up -d --build   # + HTTP gateway on :8090
```

`edge_node` logs `emitted N CoT`. The markers show in TAK through the relay, and in the relay's
`http://localhost:8088/streams` view under `<ORG>/tak/cot`.

## Env

| var | default | meaning |
| --- | --- | --- |
| `EDGE_MODE` | `both` | `imagery` / `telemetry` / `both` |
| `EDGE_NODE_ID` | `edge-ai-01` | provenance id in UID + CoT |
| `EDGE_DETECTOR` | `mock` | `mock` / `onnx` |
| `EDGE_MODEL` | — | path to `.onnx` (onnx backend) |
| `EDGE_LABELS` | COCO | newline label file (onnx backend) |
| `EDGE_CONF` | `0.35` | min confidence to emit |
| `EDGE_COT_AFFIL` | `h` | CoT affiliation letter (`h` hostile / `u` unknown / `f` friendly / `n` neutral) |
| `EDGE_COT_STALE_S` | `30` | CoT stale window |
| `EDGE_TELEM_MAX_HZ` | `1.0` | per-source throttle in telemetry mode |
| `EDGE_IMAGERY_KE` / `EDGE_SENSOR_KE` / `EDGE_COT_KE` / `EDGE_DET_KE` | see code | key expressions |
| `EDGE_API_HOST` / `EDGE_API_PORT` / `EDGE_API_TOKEN` | `127.0.0.1` / `8090` / — | gateway bind + optional `Bearer` auth |
| `frame_publisher`: `EDGE_CAM_ID`, `EDGE_FRAME_W/H`, `EDGE_FRAME_FPS`, `EDGE_HFOV_DEG`, `EDGE_ALT_AGL_M`, `EDGE_TGT_LAT/LON`, `EDGE_ORBIT_R_M` | | scene params |

## Plug in a real model

1. Add `onnxruntime>=1.17` to `demo/edge_ai/Dockerfile` (uncomment the line) and put
   your `model.onnx` in `demo/edge_ai/models/` (mounted at `/models`, git-ignored).
2. `docker compose --profile edge up -d --build edge-ai` with
   `EDGE_DETECTOR=onnx` and `EDGE_MODEL=/models/model.onnx`.
3. `OnnxYoloDetector` handles single-output `[n,85]` (YOLOv5/8 raw) or `[n,6]`
   (`x1,y1,x2,y2,conf,cls`). For other layouts, implement a class with
   `name` + `detect(rgb_ndarray) -> list[Detection]` and wire it in
   `load_detector()`.
4. Replace the mock EO feed with a real one by publishing the
   `<ORG>/imagery/v1/<cam>` schema above from your platform/GCS (or POST frames
   through `api_gateway.py`).

## Geolocation

Pinhole camera + **flat local ground plane** at the platform's ground elevation.
Pixel → angular offset from boresight via `hfov`/`vfov`; ray depression =
`-(gimbal_el + pixel_elev_offset)`; ground range = `alt_agl / tan(depression)`;
destination point from platform along `yaw + pixel_az_offset`. `ce_m` grows with
range and shallow look-angle. Good to a few tens of metres for typical ISR
geometry; **for production swap in a DEM/DTED ray-cast and real camera
intrinsics/lens distortion.** Looking at/above the horizon → falls back to the
platform nadir point with a large CE.

## Security / ACL

- The node presents the org mTLS cert (`certs/`), same as every other peer. On
  the real fabric the router ACL must grant this identity **write** scope on
  `<ORG>/tak/cot/v1/**` and `<ORG>/edge/ai/v1/**`, and **read** on the intake
  keys. Keep it least-privilege — it never needs to write `sensor/v1`.
- Every marker is auditable: the `edge/ai/v1/det/**` sidecar + the CoT
  `<_flow-tags_>` record which node/model produced it from which source key.
- `api_gateway.py` binds loopback by default and has optional bearer-token auth;
  put a real authenticating reverse proxy in front before exposing it, and give
  it its own scoped identity if it runs off-node.
- Detections are advisory. Affiliation defaults to `h` (hostile) to match the
  demo; set `EDGE_COT_AFFIL=u` if downstream should treat edge-AI output as
  unconfirmed.
