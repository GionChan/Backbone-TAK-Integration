"""Tests for tools/make_relay_package.py: the ZIP a field device unzips and self-installs.

These caught real bugs during manual smoke-testing (a Windows-path backslash embedded in a
python -c one-liner, a stale $LASTEXITCODE misreporting a successful install as failed) that
a content/structure check alone would not have -- hence the PowerShell parse tests below.
"""
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_DIR = REPO_ROOT / "relay"
ORG = "0123456789abcdef0123456789abcdef"  # fake slot; the fake cert has no CN
sys.path.insert(0, str(REPO_ROOT / "tools"))
import make_relay_package as pkg  # noqa: E402

GENERATED_PS1 = {
    "bootstrap.ps1": pkg.BOOTSTRAP_PS1,
    "run.ps1": pkg.RUN_PS1,
    "install.ps1": pkg.INSTALL_PS1,
    "uninstall.ps1": pkg.UNINSTALL_PS1,
}
GENERATED_CMD = {
    "install.cmd": pkg.INSTALL_CMD,
    "uninstall.cmd": pkg.UNINSTALL_CMD,
}


def _fake_cert_dir(tmp) -> Path:
    d = Path(tmp) / "certs"
    d.mkdir(exist_ok=True)
    (d / f"{ORG}-cert.pem").write_text("fake-cert")
    (d / f"{ORG}-key.pem").write_text("fake-key")
    (d / "efdi-ca-root.pem").write_text("fake-ca")
    return d


def _build(tmp, **overrides) -> str:
    kwargs = dict(system="unit-test-device", cert_dir=str(_fake_cert_dir(tmp)),
                  out=str(Path(tmp) / "out.zip"), tak_host="127.0.0.1", tak_udp_port=6969,
                  tak_port=8087, tak_ingest=True, tak_udp_in_port=6971, router=pkg._ROUTER_MTLS)
    kwargs.update(overrides)
    pkg.build_package(**kwargs)
    return kwargs["out"]


class FindCertTests(unittest.TestCase):
    def test_finds_bundle_and_org(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = _fake_cert_dir(tmp)
            cert, key, ca = pkg.identity.find_bundle(str(d))
            self.assertEqual(Path(cert).name, f"{ORG}-cert.pem")
            self.assertEqual(Path(key).name, f"{ORG}-key.pem")
            self.assertEqual(ca, str(d / "efdi-ca-root.pem"))
            self.assertEqual(pkg.identity.org_for(cert), ORG)

    def test_missing_cert_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(pkg.identity.find_bundle(tmp), (None, None, None))

    def test_two_identities_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = _fake_cert_dir(tmp)
            (d / "other-cert.pem").write_text("x")
            (d / "other-key.pem").write_text("x")
            self.assertEqual(pkg.identity.find_bundle(str(d)), (None, None, None))


class BuildPackageTests(unittest.TestCase):
    def test_contains_expected_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            with zipfile.ZipFile(_build(tmp)) as z:
                names = set(z.namelist())
            for f in pkg.APP_FILES:
                self.assertIn(f"app/{f}", names)
            for f in (f"certs/{ORG}-cert.pem", f"certs/{ORG}-key.pem",
                      "certs/efdi-ca-root.pem", "device.env", "README.md",
                      *GENERATED_PS1, *GENERATED_CMD):
                self.assertIn(f, names)

    def test_app_files_exist_in_repo(self):
        for f in pkg.APP_FILES:
            self.assertTrue((APP_DIR / f).is_file(), f"relay/{f} missing from repo")

    def test_app_files_cover_every_sibling_import(self):
        # The actual bug this guards against: video_relay.py existed, was imported by
        # tak_gateway.py, and worked in every local/Docker test -- but was never added to
        # APP_FILES, so every field-device package silently shipped without it and would have
        # crashed on the very first line with ModuleNotFoundError. The other direction
        # (test_app_files_exist_in_repo) can't catch a *missing* entry, only a stale one.
        # Checked transitively over every packaged module (goat_connect.py imports identity.py).
        siblings = {p.stem for p in APP_DIR.glob("*.py")}
        imported = set()
        for f in pkg.APP_FILES:
            source = (APP_DIR / f).read_text(encoding="utf-8")
            imported |= set(re.findall(r"^\s*import (\w+)", source, re.MULTILINE)) & siblings
        self.assertIn("identity", imported, "import scan found nothing -- update this test's pattern")
        missing = {f"{name}.py" for name in imported} - set(pkg.APP_FILES)
        self.assertEqual(missing, set(), f"packaged modules import these but APP_FILES doesn't list them: {missing}")

    def test_device_env_substitution(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = _build(tmp, system="my-device", tak_udp_port=1234, tak_ingest=False)
            with zipfile.ZipFile(out) as z:
                env = z.read("device.env").decode()
            self.assertIn("GATEWAY_SYSTEM=my-device", env)
            self.assertIn("TAK_UDP_PORT=1234", env)
            self.assertIn("TAK_INGEST=0", env)
            self.assertIn(f"GOAT_ORG={ORG}", env)

    def test_readme_mentions_system_and_ports(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = _build(tmp, system="my-device", tak_port=9999)
            with zipfile.ZipFile(out) as z:
                readme = z.read("README.md").decode()
            self.assertIn("my-device", readme)
            self.assertIn("9999", readme)

    def test_missing_certs_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit):
                pkg.build_package(system="x", cert_dir=tmp, out=str(Path(tmp) / "o.zip"),
                                   tak_host="127.0.0.1", tak_udp_port=6969, tak_port=8087,
                                   tak_ingest=True, tak_udp_in_port=6971, router=pkg._ROUTER_MTLS)

    def test_rebuild_overwrites_cleanly(self):
        # A device re-shipped with new settings (e.g. after editing --tak-port) must not
        # merge with the old zip's contents.
        with tempfile.TemporaryDirectory() as tmp:
            out = _build(tmp, tak_port=1111)
            out2 = _build(tmp, tak_port=2222)
            self.assertEqual(out, out2)
            with zipfile.ZipFile(out) as z:
                env = z.read("device.env").decode()
            self.assertIn("TAK_PORT=2222", env)
            self.assertNotIn("TAK_PORT=1111", env)


class PowerShellSyntaxTests(unittest.TestCase):
    """Parses (never runs) every generated .ps1 with PowerShell's own parser. Catches
    quoting/templating mistakes -- e.g. a Windows path's backslashes breaking a python -c
    one-liner embedded in a PS1 string, which this suite caught during development -- without
    needing a real Windows install cycle. Skipped if no PowerShell is on PATH."""

    @classmethod
    def setUpClass(cls):
        # pwsh (7+) has correct no-BOM UTF-8 detection; legacy powershell.exe (5.1) guesses the
        # system codepage for non-ASCII no-BOM files and can misparse otherwise-valid scripts
        # (confirmed against this repo's own setup.ps1). Our generated content is ASCII-only
        # so either works for it, but prefer pwsh to avoid that false-positive class entirely.
        cls.ps = shutil.which("pwsh") or shutil.which("powershell")
        if not cls.ps:
            raise unittest.SkipTest("no pwsh/powershell on PATH")
        cls.checker = str(Path(__file__).resolve().parent / "ps_syntax_check.ps1")

    def _assert_parses(self, name, content):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / name
            target.write_text(content, encoding="utf-8")
            r = subprocess.run(
                [self.ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", self.checker,
                 "-Target", str(target)],
                capture_output=True, text=True, timeout=30)
            self.assertEqual(r.returncode, 0, f"{name} failed to parse:\n{r.stdout}{r.stderr}")

    def test_generated_ps1_parse(self):
        for name, content in GENERATED_PS1.items():
            with self.subTest(name=name):
                self._assert_parses(name, content)

    def test_demo_ps1_parse(self):
        for f in sorted((REPO_ROOT / "demo").glob("*.ps1")):
            with self.subTest(name=f.name):
                self._assert_parses(f.name, f.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
