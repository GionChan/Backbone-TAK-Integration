"""relay/doctor.py runs without zenoh, never crashes on a bare machine and names failures."""
import io
import os
import socket
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "relay"))
import doctor  # noqa: E402


class DoctorTests(unittest.TestCase):
    def _run(self, env):
        doctor.RESULTS.clear()
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as empty, mock.patch.dict(os.environ, {"GOAT_CERT_DIR": empty, **env}), \
                mock.patch.object(doctor.shutil, "which", return_value=None), redirect_stdout(out):
            code = doctor.main()
        return code, out.getvalue()

    def test_offline_machine_reports_without_crashing(self):
        code, out = self._run({"GOAT_LOCAL_ROUTER": "tcp/127.0.0.1:1", "GATEWAY_HTTP_PORT": "1"})
        self.assertIn("certificate bundle", out)
        self.assertIn("local router", out)
        self.assertIn(code, (0, 1))

    def test_busy_port_is_a_failure(self):
        with socket.socket() as s:
            s.bind(("", 0))
            s.listen(1)
            port = s.getsockname()[1]
            code, out = self._run({"TAK_PORT": str(port), "GATEWAY_HTTP_PORT": "1",
                                   "GOAT_LOCAL_ROUTER": "tcp/127.0.0.1:1"})
        self.assertEqual(code, 1)
        self.assertIn(f"port {port}/tcp: in use", out)

    def test_server_ingest_is_warned(self):
        _, out = self._run({"TAK_INGEST": "1", "TAK_INGEST_FROM": "local,server", "GATEWAY_HTTP_PORT": "1",
                            "GOAT_LOCAL_ROUTER": "tcp/127.0.0.1:1"})
        self.assertIn("[WARN] PLI to backbone", out)


if __name__ == "__main__":
    unittest.main()
