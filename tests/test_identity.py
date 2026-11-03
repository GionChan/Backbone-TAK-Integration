"""Tests for relay/identity.py: bundle discovery and org-slot resolution."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "relay"))
import identity  # noqa: E402

SLOT = "0123456789abcdef0123456789abcdef"


def _bundle(d: Path, prefix: str, ca="efdi-ca-root.pem"):
    (d / f"{prefix}-cert.pem").write_text("c")
    (d / f"{prefix}-key.pem").write_text("k")
    if ca:
        (d / ca).write_text("a")


class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {}, clear=False)
        self.env.start()
        for k in ("GOAT_ORG", "GOAT_CERT", "GOAT_KEY", "GOAT_CA", "GOAT_CERT_DIR"):
            os.environ.pop(k, None)

    def tearDown(self):
        self.env.stop()

    def test_slot_from_file_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            _bundle(Path(tmp), SLOT)
            cert, _, _ = identity.find_bundle(tmp)
            self.assertEqual(identity.org_for(cert), SLOT)

    def test_handle_prefix_needs_goat_org(self):
        with tempfile.TemporaryDirectory() as tmp:
            _bundle(Path(tmp), "some-handle")
            cert, _, _ = identity.find_bundle(tmp)
            self.assertEqual(identity.org_for(cert), "")
            os.environ["GOAT_ORG"] = SLOT
            self.assertEqual(identity.org_for(cert), SLOT)

    def test_ca_fallback_to_other_pem(self):
        with tempfile.TemporaryDirectory() as tmp:
            _bundle(Path(tmp), SLOT, ca="roots.pem")
            self.assertTrue(identity.find_bundle(tmp)[2].endswith("roots.pem"))

    def test_cert_dir_env_is_exclusive(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["GOAT_CERT_DIR"] = tmp
            self.assertEqual(identity.cert_dirs(), [tmp])
            self.assertEqual(identity.resolve_bundle(), (None, None, None))

    def test_explicit_paths_win(self):
        os.environ.update(GOAT_CERT="c", GOAT_KEY="k", GOAT_CA="a")
        self.assertEqual(identity.resolve_bundle(), ("c", "k", "a"))


    def test_router_from_bundle_notes(self):
        with tempfile.TemporaryDirectory() as tmp:
            _bundle(Path(tmp), SLOT)
            (Path(tmp) / "NOTES.md").write_text("Org: x\nRouter endpoint:     tls/router.example:7447\n")
            cert = identity.find_bundle(tmp)[0]
            self.assertEqual(identity.router_for(cert), "tls/router.example:7447")
            os.environ["GOAT_ROUTER"] = "tls/override:7447"
            self.assertEqual(identity.router_for(cert), "tls/override:7447")
        os.environ.pop("GOAT_ROUTER")
        self.assertEqual(identity.router_for(None), identity.DEFAULT_ROUTER)

    def test_downloaded_bundle_used_only_when_unambiguous(self):
        with tempfile.TemporaryDirectory() as home, \
                mock.patch.object(identity, "cert_dirs", return_value=[]), \
                mock.patch("os.path.expanduser", return_value=home):
            first = Path(home, "Downloads", "efdi-onboarding-a")
            first.mkdir(parents=True)
            _bundle(first, SLOT)
            self.assertTrue(identity.resolve_bundle()[0].startswith(str(first)))
            second = Path(home, "Downloads", "efdi-onboarding-b")
            second.mkdir()
            _bundle(second, SLOT)
            self.assertEqual(identity.resolve_bundle(), (None, None, None))


if __name__ == "__main__":
    unittest.main()
