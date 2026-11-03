"""Integration test of relay/tak_gateway.py against the local router (no mesh needed).

Needs: docker compose --profile demo up -d zenoh-router (tcp/127.0.0.1:7447). Run: python tests/e2e_gateway.py
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import zenoh

ROOT = Path(__file__).resolve().parent.parent
ORG = "0123456789abcdef0123456789abcdef"


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def cot(uid, typ="a-h-A", stale=30, lat="50.7", lon="-2.4"):
    now = datetime.now(timezone.utc)
    return (f'<event version="2.0" uid="{uid}" type="{typ}" time="{iso(now)}" start="{iso(now)}" '
            f'stale="{iso(now + timedelta(seconds=stale))}"><point lat="{lat}" lon="{lon}" hae="0" ce="1" le="1"/></event>').encode()


def main():
    try:
        socket.create_connection(("127.0.0.1", 7447), timeout=2).close()
    except OSError:
        if os.environ.get("E2E_REQUIRED") == "1":
            print("FAIL: local router not running")
            return 1
        print("SKIP: local router not running")
        return 0
    tmp = tempfile.mkdtemp()
    env = dict(os.environ, GOAT_ROUTER="tcp/127.0.0.1:7447", TAK_HOST="127.0.0.1",
               TAK_UDP_PORT="16969", TAK_PORT="18087", GATEWAY_HTTP_PORT="18088", TAK_INGEST="1", GATEWAY_INGEST_ALL="1", TAK_UDP_IN_PORT="16971")
    for k in ("GOAT_CERT", "GOAT_KEY", "GOAT_CA"):
        env.pop(k, None)
    # an empty cert dir forces the local router even when ./certs holds a real bundle
    env.update(GOAT_CERT_DIR=tmp, GOAT_ORG=ORG, GOAT_LOCAL_ROUTER="tcp/127.0.0.1:7447")
    gw = subprocess.Popen([sys.executable, "-u", str(ROOT / "relay" / "tak_gateway.py")], env=env,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    results = {}
    try:
        time.sleep(6)
        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp.bind(("127.0.0.1", 16969))
        udp.settimeout(0.5)
        tcp = socket.create_connection(("127.0.0.1", 18087), timeout=5)
        tcp.settimeout(0.5)

        c = zenoh.Config()
        c.insert_json5("mode", '"client"')
        c.insert_json5("connect/endpoints", json.dumps(["tcp/127.0.0.1:7447"]))
        s = zenoh.open(c)
        pli = []
        s.declare_subscriber(f"{ORG}/tak/pli/v1/**", lambda x: pli.append(bytes(x.payload)))
        time.sleep(1)

        s.put("vendorX/tak/cot/v1/good", cot("good-1"))            # forwarded
        s.put("vendorX/tak/cot/v1/bad", b"<event uid='x'>")        # invalid XML
        s.put("vendorX/tak/cot/v1/stale", cot("old-1", stale=-30))  # already stale
        s.put(f"{ORG}/sensor/v1/drone1", json.dumps({"source": "drone1", "lat": 60.1, "lon": 25.1, "alt": 100,
                                                    "heading": 90, "speed_kmh": 36, "phase": "orbit"}).encode())
        s.put("vendorY/geo/track/v1/7", json.dumps({"schema": "goat.geo.track.v1", "id": "t7", "lat": 50.0, "lon": 8.3,
                                                     "alt_m": 100, "course_deg": 10, "speed_mps": 5, "dimension": "air",
                                                     "affiliation": "unknown"}).encode())
        s.put("vendorM/telemetry", json.dumps({"mavpackettype": "GLOBAL_POSITION_INT", "lat": 393900684,
                                                "lon": -71055635, "alt": 1000, "hdg": 0, "src_system": 7}).encode())
        s.put("vendorZ/whatever/v1", cot("odd-key-1"))              # CoT on a non-standard key
        s.put("vendorW/big-video-feed", bytes(1000))           # skipped by key + not recognisable
        import struct
        ident = b'demo-xyz'
        pb = (bytes([0x0A, len(ident)]) + ident + bytes([0x10, 0x01]) +
              bytes([0x19]) + struct.pack('<d', 29.3) + bytes([0x21]) + struct.pack('<d', 47.8) +
              bytes([0x42, 3]) + b'air')
        s.put("release/REL/h/sys/fob/tracks/v1", pb)
        tcp.sendall(cot("tak-user-1", typ="a-f-G-U-C") + cot("hostile-x", typ="a-h-G"))  # PLI in; hostile not ingested
        us = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        us.sendto(cot("udp-user-1", typ="a-f-G-U-C"), ("127.0.0.1", 16971))
        us.sendto(cot("udp-hostile", typ="a-h-G"), ("127.0.0.1", 16971))
        time.sleep(3)

        udp_got = []
        try:
            while True:
                udp_got.append(udp.recvfrom(65535)[0])
        except socket.timeout:
            pass
        tcp_got = b""
        try:
            while True:
                chunk = tcp.recv(65535)
                if not chunk:
                    break
                tcp_got += chunk
        except socket.timeout:
            pass

        health = urllib.request.urlopen("http://127.0.0.1:18088/healthz", timeout=5)
        metrics = urllib.request.urlopen("http://127.0.0.1:18088/metrics", timeout=5).read().decode()

        results["udp has good"] = any(b'uid="good-1"' in d for d in udp_got)
        results["any-key CoT forwarded"] = any(b'uid="odd-key-1"' in d for d in udp_got)
        results["geotrack converted"] = any(b'uid="GEO.t7"' in d for d in udp_got)
        results["mavlink converted"] = any(b'uid="MAV.7"' in d for d in udp_got)
        results["protobuf track converted"] = any(b'uid="PB.demo-xyz"' in d for d in udp_got)
        results["udp has telemetry cot"] = any(b'uid="drone1"' in d for d in udp_got)
        results["udp lacks bad/stale"] = not any(b"old-1" in d or b"uid='x'" in d for d in udp_got)
        results["tcp mirrors udp"] = b'uid="good-1"' in tcp_got
        results["healthz 200"] = health.status == 200
        results["metrics has dropped stale"] = 'reason="already-stale"' in metrics
        results["ingest: friendly PLI published"] = any(b'uid="tak-user-1"' in p for p in pli)
        results["ingest via UDP input"] = any(b'uid="udp-user-1"' in p for p in pli)
        results["ingest via UDP: hostile not published"] = not any(b"udp-hostile" in p for p in pli)
        results["own PLI is not echoed back to TAK outputs"] = not any(b'uid="tak-user-1"' in d for d in udp_got)
        results["ingest: hostile not published"] = not any(b"hostile-x" in p for p in pli)
    except Exception as exc:  # noqa: BLE001
        results[f'test crashed: {exc!r}'] = False
    finally:
        gw.terminate()
        try:
            out = gw.communicate(timeout=5)[0]
        except subprocess.TimeoutExpired:
            gw.kill()
            out = ""
    for k, v in results.items():
        print(("PASS" if v else "FAIL"), k)
    if not all(results.values()):
        print(out[-1500:])
        return 1
    print("GATEWAY E2E PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
