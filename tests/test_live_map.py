"""demo/live_map.py: on the real fabric /inject needs the token; JSON only."""
import json
import socket
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "demo"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "relay"))
try:
    import live_map  # noqa: E402
except ImportError as exc:  # eclipse-zenoh not installed
    raise unittest.SkipTest(f"live_map not importable: {exc}")


class InjectTests(unittest.TestCase):
    def setUp(self):
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), live_map._Handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.shutdown)
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"
        self.sender = mock.Mock()
        p = mock.patch.object(live_map, "_sender", self.sender)
        p.start()
        self.addCleanup(p.stop)

    def _post(self, headers):
        body = json.dumps({"source": "uav-1", "lat": 60.1, "lon": 25.0, "alt": 100}).encode()
        req = urllib.request.Request(self.base + "/inject", data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code

    def test_real_fabric_needs_the_token(self):
        with mock.patch.object(live_map, "_REAL", True), mock.patch.object(live_map, "_INJECT_TOKEN", "t0k"):
            self.assertEqual(self._post({"Content-Type": "application/json"}), 403)
            self.assertEqual(self._post({"Content-Type": "application/json", "X-Inject-Token": "bad"}), 403)
            self.assertEqual(self._post({"Content-Type": "application/json", "X-Inject-Token": "t0k"}), 200)
        self.assertEqual(self.sender.track.call_count, 1)

    def test_real_fabric_without_a_token_set_refuses(self):
        with mock.patch.object(live_map, "_REAL", True), mock.patch.object(live_map, "_INJECT_TOKEN", ""):
            self.assertEqual(self._post({"Content-Type": "application/json", "X-Inject-Token": ""}), 403)
        self.sender.track.assert_not_called()

    def test_local_router_needs_no_token_but_json(self):
        with mock.patch.object(live_map, "_REAL", False):
            self.assertEqual(self._post({"Content-Type": "text/plain"}), 415)
            self.assertEqual(self._post({"Content-Type": "application/json"}), 200)

    def test_control_page_with_token_query(self):
        with urllib.request.urlopen(self.base + "/control?token=abc", timeout=5) as r:
            self.assertIn(b"X-Inject-Token", r.read())


if __name__ == "__main__":
    unittest.main()
