"""Integration test of the TAK modes with the real relay process against the local router.

multicast: backbone -> group (tagged), own device published, neighbour not, own output not re-published.
server:    only the TAK Server output, backbone -> server, server users not published,
           and the relay refuses to start without TAK_SERVER.

Needs a local router on tcp/127.0.0.1:7447 (python demo/local_router.py). Run: python tests/e2e_modes.py
Without a router it prints SKIP and exits 0, unless E2E_REQUIRED=1 (CI), then it fails.
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

import zenoh

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "relay"))
import backbone_cot as bc  # noqa: E402

ROUTER = "tcp/127.0.0.1:7447"
RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok)))
    print(("PASS " if ok else "FAIL ") + name + (f"  ({detail})" if detail and not ok else ""), flush=True)


def free_port(kind=socket.SOCK_STREAM):
    with socket.socket(socket.AF_INET, kind) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_relay(env, http):
    e = dict(os.environ, GOAT_CERT_DIR=tempfile.mkdtemp(), GOAT_LOCAL_ROUTER=ROUTER, GOAT_ORG="local",
             GATEWAY_HTTP_PORT=str(http), TAK_PORT=str(free_port()), TAK_INGEST="1", GATEWAY_HEARTBEAT="0",
             TAK_UDP_IN_PORT="0", **env)
    for k in ("GOAT_CERT", "GOAT_KEY", "GOAT_CA", "GOAT_ROUTER", "TAK_INGEST_FROM", "TAK_INGEST_UIDS"):
        if k not in env:
            e.pop(k, None)
    return subprocess.Popen([sys.executable, "-u", str(ROOT / "relay" / "tak_gateway.py")], env=e,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def stop(p):
    p.terminate()
    try:
        return p.communicate(timeout=15)[0]
    except subprocess.TimeoutExpired:
        p.kill()
        return p.communicate()[0]


def status(http, wait=20.0):
    end = time.time() + wait
    while True:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{http}/status", timeout=3) as r:
                return json.load(r)
        except OSError:
            if time.time() > end:
                raise
            time.sleep(0.5)


def wait_connected(http, wait=20.0):
    end = time.time() + wait
    while time.time() < end:
        st = status(http)
        if st["gauges"].get("gateway_fabric_up"):
            return st
        time.sleep(0.5)
    return status(http)


def telemetry(s, uid):
    s.put(f"local/sensor/v1/{uid}", json.dumps({"source": uid, "lat": 60.1, "lon": 24.9, "alt": 100}))


def test_multicast(s, pli):
    group, port = "239.255.77.1", free_port(socket.SOCK_DGRAM)
    mc = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    mc.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if hasattr(socket, "SO_REUSEPORT"):
        mc.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    mc.bind(("", port))
    mc.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, socket.inet_aton(group) + socket.inet_aton("127.0.0.1"))
    mc.settimeout(1)
    http = free_port()
    p = start_relay({"TAK_MODE": "multicast", "TAK_MULTICAST_GROUP": f"{group}:{port}",
                     "TAK_MULTICAST_IF": "127.0.0.1", "TAK_INGEST_UIDS": "ANDROID-own"}, http)
    try:
        st = wait_connected(http)
        check("multicast: mode in /status", st.get("mode") == "multicast", st.get("mode"))
        check("multicast: output named", any(o["name"].startswith("multicast:") for o in st["outputs"]))
        got = None
        for _ in range(10):
            telemetry(s, "uav-mc")
            try:
                while got is None:
                    data, _ = mc.recvfrom(65535)
                    if b"uav-mc" in data:
                        got = data
            except socket.timeout:
                pass
            if got:
                break
        check("multicast: backbone -> group", got is not None)
        check("multicast: sent CoT is tagged", bool(got) and b"<__efdi_relay/>" in got)
        tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        tx.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton("127.0.0.1"))
        tx.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
        for uid in ("ANDROID-own", "ANDROID-neighbour"):
            tx.sendto(bc.make_cot(uid, "a-f-G-U-C", 60.2, 25.0), (group, port))
        end = time.time() + 5
        while time.time() < end and "local/tak/pli/v1/ANDROID-own" not in pli:
            time.sleep(0.2)
        check("multicast: own device published", "local/tak/pli/v1/ANDROID-own" in pli, pli)
        check("multicast: neighbour not published", not any("neighbour" in k for k in pli), pli)
        c = status(http)["counters"]
        check("multicast: relay's own output not re-published",
              c.get('gateway_ingest_dropped_total{reason="relayed"}', 0) >= 1, c)
    finally:
        out = stop(p)
        mc.close()
    if any(not ok for n, ok in RESULTS if n.startswith("multicast")):
        print(out[-3000:])


def test_server(s, pli):
    pli.clear()
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    sport = srv.getsockname()[1]
    conns = []
    threading.Thread(target=lambda: conns.append(srv.accept()[0]), daemon=True).start()
    http = free_port()
    p = start_relay({"TAK_MODE": "server", "TAK_SERVER": f"127.0.0.1:{sport}", "TAK_SERVER_TLS": "0"}, http)
    try:
        st = wait_connected(http)
        names = [o["name"] for o in st["outputs"]]
        check("server: only the TAK Server output", names == [f"tcp_client:127.0.0.1:{sport}"], names)
        end = time.time() + 10
        while time.time() < end and not status(http)["outputs"][0]["connected"]:
            time.sleep(0.3)
        check("server: connected", status(http)["outputs"][0]["connected"])
        buf = b""
        if conns:
            conn = conns[0]
            conn.settimeout(1)
            for _ in range(10):
                telemetry(s, "uav-srv")
                try:
                    buf += conn.recv(65535)
                except socket.timeout:
                    pass
                if b"uav-srv" in buf:
                    break
            conn.sendall(bc.make_cot("ANDROID-server-user", "a-f-G-U-C", 60.3, 25.1))
        check("server: backbone -> TAK Server", b"uav-srv" in buf)
        end = time.time() + 5
        while time.time() < end and not status(http)["counters"].get('gateway_ingest_dropped_total{reason="not-local"}'):
            time.sleep(0.2)
        check("server: TAK Server user not published", pli == [], pli)
        check("server: counted as not-local",
              status(http)["counters"].get('gateway_ingest_dropped_total{reason="not-local"}', 0) >= 1)
    finally:
        out = stop(p)
        srv.close()
    if any(not ok for n, ok in RESULTS if n.startswith("server")):
        print(out[-3000:])

    p = start_relay({"TAK_MODE": "server", "TAK_SERVER": ""}, free_port())
    try:
        out = p.communicate(timeout=30)[0]
    except subprocess.TimeoutExpired:
        out = stop(p)
    check("server: refuses to start without TAK_SERVER", p.returncode not in (0, None) and "TAK_SERVER" in out,
          out[-300:])


def main():
    try:
        socket.create_connection(("127.0.0.1", 7447), timeout=2).close()
    except OSError:
        if os.environ.get("E2E_REQUIRED") == "1":
            print("FAIL: local router not running")
            return 1
        print("SKIP: local router not running")
        return 0
    c = zenoh.Config()
    c.insert_json5("mode", '"client"')
    c.insert_json5("connect/endpoints", json.dumps([ROUTER]))
    s = zenoh.open(c)
    pli = []
    s.declare_subscriber("local/tak/pli/v1/**", lambda smp: pli.append(str(smp.key_expr)))
    try:
        test_multicast(s, pli)
        test_server(s, pli)
    finally:
        s.close()
    failed = [n for n, ok in RESULTS if not ok]
    print("\nMODES E2E PASSED" if not failed else f"\nMODES E2E FAILED: {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
