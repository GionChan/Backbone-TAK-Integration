"""Unit tests for relay/tak_gateway.py behaviour that has no I/O beyond loopback sockets."""
import json
import os
import socket
import sys
import time
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "relay"))
try:
    import tak_gateway as gw
except ImportError as exc:  # eclipse-zenoh not installed
    raise unittest.SkipTest(f"tak_gateway not importable: {exc}")
import cot_guard  # noqa: E402


class _Sample:
    def __init__(self, body: dict):
        self.payload = mock.Mock(to_bytes=lambda: json.dumps(body).encode())


class _Capture:
    name = "capture"

    def __init__(self):
        self.sent = []

    def send(self, data):
        self.sent.append(data)

    def status(self):
        return {"name": self.name, "connected": True}


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class TelemetryTests(unittest.TestCase):
    def setUp(self):
        self.out = _Capture()
        gw.OUTPUTS[:] = [self.out]

    def tearDown(self):
        gw.OUTPUTS[:] = []

    def test_markup_in_payload_is_escaped(self):
        data = gw.telemetry_to_cot({"source": 'x"/><evil a="', "lat": 60.1, "lon": 24.9, "phase": "<b>"})
        ok, reason = cot_guard.validate_cot(data)
        self.assertTrue(ok, reason)
        self.assertEqual(ET.fromstring(data.split(b"?>", 1)[1]).get("uid"), 'x"-><evil a="')

    def test_valid_telemetry_is_dispatched(self):
        gw.on_telemetry(_Sample({"source": "uav-1", "lat": 60.1, "lon": 24.9, "alt": 100}))
        self.assertEqual(len(self.out.sent), 1)

    def test_lost_track_still_reaches_tak(self):
        # "lost" is stale on purpose so TAK removes the track; validation must not drop it.
        gw.on_telemetry(_Sample({"source": "uav-1", "lat": 60.1, "lon": 24.9, "lost": True}))
        self.assertEqual(len(self.out.sent), 1)

    def test_bad_telemetry_is_counted_not_raised(self):
        gw.on_telemetry(_Sample({"source": "uav-1", "lat": None, "lon": 24.9}))
        self.assertEqual(self.out.sent, [])


class ConfigTests(unittest.TestCase):
    def test_udp_targets(self):
        with mock.patch.dict(os.environ, {"TAK_UDP_TARGETS": "a:1, b:2"}, clear=False):
            cfg = gw.load_config()
        udp = [o for o in cfg["outputs"] if o["type"] == "udp"]
        self.assertEqual([(o["host"], o["port"]) for o in udp], [("a", 1), ("b", 2)])

    def test_legacy_single_target(self):
        env = {"TAK_HOST": "h", "TAK_UDP_PORT": "7"}
        with mock.patch.dict(os.environ, env, clear=False):
            os.environ.pop("TAK_UDP_TARGETS", None)
            cfg = gw.load_config()
        self.assertIn({"type": "udp", "host": "h", "port": 7}, cfg["outputs"])


class TcpServerOutputTests(unittest.TestCase):
    def test_stalled_client_does_not_block_others(self):
        port = _free_port()
        out = gw.TcpServerOutput({"port": port})
        stalled = socket.create_connection(("127.0.0.1", port))  # never reads
        stalled.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
        reader = socket.create_connection(("127.0.0.1", port))
        reader.settimeout(5)
        deadline = time.time() + 5
        while out.status()["clients"] < 2 and time.time() < deadline:
            time.sleep(0.05)
        self.assertEqual(out.status()["clients"], 2)

        frame = b"<event/>" + b" " * 1024
        t0 = time.time()
        for _ in range(3000):  # ~3 MB: far more than the stalled peer's buffers hold
            out.send(frame)
        self.assertLess(time.time() - t0, 2.0, "send() blocked on a stalled client")

        got = 0
        while got < 64 * 1024:
            got += len(reader.recv(65536))
        stalled.close()
        reader.close()


if __name__ == "__main__":
    unittest.main()
