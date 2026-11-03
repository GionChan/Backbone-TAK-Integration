#!/usr/bin/env python3
"""HTTP <-> EFDI backbone gateway - the 'API rajapinta' for an edge-AI box
that does not speak Zenoh.

  GET  /healthz                 -> {"ok": true, "fabric": "efdi-mtls"|"local"}
  GET  /keys?ke=<expr>&secs=3   -> {"keys": {...counts...}}  (sniff live keys)
  GET  /intake/frames           -> text/event-stream of <ORG>/imagery/v1/** JSON
  GET  /intake/telemetry        -> text/event-stream of <ORG>/sensor/v1/** JSON
  POST /detections/cot          -> publish to <ORG>/tak/cot/v1/<uid>
        body application/xml  : raw CoT 2.0 (uid taken from the <event uid=...>)
        body application/json : {uid?,label,conf,lat,lon,hae?,course?,speed_ms?,
                                 ce_m?,parent_uid?}  -> CoT built server-side

Stdlib only. Bind is loopback by default; put a real authenticating proxy in
front before exposing it. Auth: set EDGE_API_TOKEN to require Authorization:
Bearer <token> on every route except /healthz.
"""
from __future__ import annotations

import json
import os
import queue
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import zenoh  # noqa: E402
from cot import build_cot  # noqa: E402
from fabric import ORG, open_session  # noqa: E402

HOST = os.environ.get("EDGE_API_HOST", "127.0.0.1")
PORT = int(os.environ.get("EDGE_API_PORT", "8090"))
TOKEN = os.environ.get("EDGE_API_TOKEN", "")
COT_KE = os.environ.get("EDGE_COT_KE", f"{ORG}/tak/cot/v1")
IMAGERY_KE = os.environ.get("EDGE_IMAGERY_KE", f"{ORG}/imagery/v1/**")
SENSOR_KE = os.environ.get("EDGE_SENSOR_KE", f"{ORG}/sensor/v1/**")

_SESS, _REAL = open_session()
_UID_RE = re.compile(r'uid="([^"]+)"')


def _authed(h: BaseHTTPRequestHandler) -> bool:
    if not TOKEN:
        return True
    return h.headers.get("Authorization", "") == f"Bearer {TOKEN}"


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):  # quieter
        pass

    def _json(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    # ---- GET ----
    def do_GET(self):
        if self.path.startswith("/healthz"):
            return self._json(200, {"ok": True, "fabric": "efdi-mtls" if _REAL else "local"})
        if not _authed(self):
            return self._json(401, {"error": "unauthorized"})
        if self.path.startswith("/keys"):
            return self._keys()
        if self.path.startswith("/intake/frames"):
            return self._sse(IMAGERY_KE)
        if self.path.startswith("/intake/telemetry"):
            return self._sse(SENSOR_KE)
        return self._json(404, {"error": "not found"})

    def _keys(self):
        from urllib.parse import parse_qs, urlparse

        q = parse_qs(urlparse(self.path).query)
        ke = q.get("ke", [f"{ORG}/**"])[0]
        secs = min(float(q.get("secs", ["3"])[0]), 15.0)
        c: dict[str, int] = {}
        sub = _SESS.declare_subscriber(ke, lambda s: c.__setitem__(
            str(s.key_expr), c.get(str(s.key_expr), 0) + 1))
        time.sleep(secs)
        sub.undeclare()
        return self._json(200, {"ke": ke, "secs": secs, "keys": dict(sorted(c.items()))})

    def _sse(self, ke):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        q: queue.Queue = queue.Queue(maxsize=64)
        sub = _SESS.declare_subscriber(ke, lambda s: _offer(q, s.payload.to_bytes()))
        try:
            while True:
                try:
                    item = q.get(timeout=10)
                    self.wfile.write(b"data: " + item + b"\n\n")
                except queue.Empty:
                    self.wfile.write(b": keepalive\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            sub.undeclare()

    # ---- POST ----
    def do_POST(self):
        if not _authed(self):
            return self._json(401, {"error": "unauthorized"})
        if not self.path.startswith("/detections/cot"):
            return self._json(404, {"error": "not found"})
        n = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(n)
        ctype = self.headers.get("Content-Type", "").split(";")[0].strip()
        try:
            if ctype == "application/xml" or body.lstrip().startswith(b"<"):
                xml = body.decode("utf-8")
                m = _UID_RE.search(xml)
                uid = m.group(1) if m else f"EDGEAI.api.{int(time.time()*1000)}"
            else:
                d = json.loads(body)
                uid = d.get("uid") or f"EDGEAI.api.{d.get('label','det')}.{int(time.time()*1000)}"
                xml = build_cot(
                    uid=uid, label=d["label"], conf=float(d.get("conf", 0.8)),
                    lat=float(d["lat"]), lon=float(d["lon"]),
                    hae=float(d.get("hae", 0.0)), course=d.get("course"),
                    speed_ms=d.get("speed_ms"), ce_m=float(d.get("ce_m", 30.0)),
                    parent_uid=d.get("parent_uid"), node_id=d.get("node", "edge-ai-api"),
                    model=d.get("model", "external/1"),
                )
        except Exception as e:  # noqa: BLE001
            return self._json(400, {"error": f"bad body: {e}"})
        _SESS.put(f"{COT_KE}/{uid}", xml.encode(), encoding=zenoh.Encoding.APPLICATION_XML)
        return self._json(202, {"published": f"{COT_KE}/{uid}", "bytes": len(xml)})


def _offer(q: queue.Queue, item: bytes):
    try:
        q.put_nowait(item)
    except queue.Full:
        pass


def main():
    print(f"[api-gw] fabric={'efdi-mtls' if _REAL else 'local'}  "
          f"listen http://{HOST}:{PORT}  auth={'on' if TOKEN else 'off'}", flush=True)
    print(f"[api-gw]   GET  /intake/frames | /intake/telemetry  (SSE)", flush=True)
    print(f"[api-gw]   POST /detections/cot  -> {COT_KE}/<uid>", flush=True)
    srv = ThreadingHTTPServer((HOST, PORT), H)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
        _SESS.close()


if __name__ == "__main__":
    main()
