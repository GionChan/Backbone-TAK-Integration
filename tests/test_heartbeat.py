import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "relay"))
import heartbeat as hb  # noqa: E402


class Fake:
    def __init__(self):
        self.puts = []

    def put(self, k, v):
        self.puts.append((k, json.loads(v)))


class HeartbeatTests(unittest.TestCase):
    def test_body_matches_spec(self):
        s = Fake()
        h = hb.Heartbeat(s, "org1", "sys-a", version="2.0", interval=60, health_fn=lambda: True, log=lambda m: None)
        h.beat()
        h.beat()
        key, body = s.puts[1]
        self.assertEqual(key, "org1/sys-a/heartbeat/v1")
        self.assertEqual(set(body), {"key", "system", "status", "version", "sent_at", "seq", "interval_seconds"})
        self.assertEqual((body["seq"], body["status"], body["key"]), (2, "ok", "org1/sys-a/heartbeat/v1"))
        self.assertTrue(body["sent_at"].endswith("Z"))

    def test_degraded_when_unhealthy_or_check_raises(self):
        s = Fake()
        hb.Heartbeat(s, "o", "s", health_fn=lambda: False, log=lambda m: None).beat()
        def boom():
            raise RuntimeError("x")
        hb.Heartbeat(s, "o", "s", health_fn=boom, log=lambda m: None).beat()
        self.assertEqual([b["status"] for _, b in s.puts], ["degraded", "degraded"])

    def test_interval_bounds(self):
        for bad in (0, -1, 901):
            with self.assertRaises(ValueError):
                hb.Heartbeat(Fake(), "o", "s", interval=bad)

    def test_publish_failure_does_not_raise(self):
        class Broken:
            def put(self, *a):
                raise OSError("down")
        msgs = []
        hb.Heartbeat(Broken(), "o", "s", log=msgs.append).beat()
        self.assertTrue(any("failed" in m for m in msgs))


if __name__ == "__main__":
    unittest.main()
