"""Tests for tools/make_relay_package.py: the ZIP a field device unzips and self-installs.

These caught real bugs during manual smoke-testing (a Windows-path backslash embedded in a
python -c one-liner, a stale $LASTEXITCODE misreporting a successful install as failed) that
a content/structure check alone would not have -- hence the PowerShell parse tests below.
"""
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_DIR = REPO_ROOT / "relay"
ORG = "0123456789abcdef0123456789abcdef"  # fake slot; the fake cert has no CN
sys.path.insert(0, str(REPO_ROOT / "tools"))
import make_relay_package as pkg  # noqa: E402

GENERATED_PS1 = {
    "lang.ps1": pkg.LANG_PS1,
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
                      "certs/efdi-ca-root.pem", "device.env", "README.fi.md", "README.en.md",
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
                for name in ("README.fi.md", "README.en.md"):
                    readme = z.read(name).decode()
                    self.assertIn("my-device", readme)
                    self.assertIn("9999", readme)

    def test_choices_left_to_the_installer_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            with zipfile.ZipFile(_build(tmp)) as z:
                env = z.read("device.env").decode()
        self.assertIn("# RELAY_LANG=", env)
        self.assertIn("# TAK_MODE=", env)

    def test_preset_server_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            p12, trust = Path(tmp, "relay.p12"), Path(tmp, "truststore-root.p12")
            p12.write_bytes(b"p12")
            trust.write_bytes(b"trust")
            out = _build(tmp, lang="en", mode="server", tak_server="tak.example:8089",
                         tak_p12=str(p12), tak_trust_p12=str(trust), ingest_uids="ANDROID-1")
            with zipfile.ZipFile(out) as z:
                env = z.read("device.env").decode()
                names = set(z.namelist())
        for expected in ("RELAY_LANG=en", "TAK_MODE=server", "TAK_SERVER=tak.example:8089",
                         "TAK_SERVER_P12=certs\\tak\\relay.p12", "TAK_SERVER_TRUST_P12=certs\\tak\\truststore-root.p12",
                         "TAK_INGEST_UIDS=ANDROID-1"):
            self.assertIn(expected, env.splitlines())
        self.assertNotIn("TAK_SERVER_P12_PASSWORD=", [ln for ln in env.splitlines() if not ln.startswith("#")])
        self.assertTrue({"certs/tak/relay.p12", "certs/tak/truststore-root.p12"} <= names)

    def test_bad_mode_refused(self):
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(SystemExit):
            _build(tmp, mode="broadcast")

    def test_ps1_have_bom_and_crlf(self):
        # Windows PowerShell 5.1 reads BOM-less files in the ANSI codepage: Finnish letters break.
        with tempfile.TemporaryDirectory() as tmp:
            with zipfile.ZipFile(_build(tmp)) as z:
                for name in GENERATED_PS1:
                    raw = z.read(name)
                    self.assertTrue(raw.startswith(b"\xef\xbb\xbf"), name)
                    self.assertNotIn(b"\r\r", raw, name)
                    self.assertEqual(raw.count(b"\n"), raw.count(b"\r\n"), name)


class TemplateTests(unittest.TestCase):
    """The publishable template: no certificate, no slot, no device name."""

    def test_template_has_nothing_secret(self):
        with tempfile.TemporaryDirectory() as tmp:
            pkg.build_package(None, None, str(Path(tmp) / "t.zip"), "127.0.0.1", 6969, 8087, True, 6971,
                              template=True)
            with zipfile.ZipFile(Path(tmp) / "t.zip") as z:
                names = z.namelist()
                env = z.read("device.env").decode().splitlines()
        self.assertEqual([n for n in names if n.startswith("certs/")], ["certs/README.txt"])
        self.assertFalse([n for n in names if n.endswith((".pem", ".key", ".p12"))])
        for key in ("GOAT_ORG", "GOAT_ROUTER", "GATEWAY_SYSTEM"):
            self.assertIn(f"# {key}=", env)
            self.assertFalse([ln for ln in env if ln.startswith(f"{key}=")])

    def test_regular_package_needs_a_name(self):
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(SystemExit):
            _build(tmp, system=None)

    def test_notes_travel_with_the_certificate(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = _fake_cert_dir(tmp)
            (d / "NOTES.md").write_text("Router endpoint: tls/r.example:7447\n")
            with zipfile.ZipFile(_build(tmp)) as z:
                self.assertIn("certs/NOTES.md", z.namelist())

    def test_installer_asks_bundle_and_name_before_mode(self):
        s = pkg.INSTALL_PS1
        self.assertLess(s.index("# ---- 1. language"), s.index("# ---- 2. certificate bundle"))
        self.assertLess(s.index("# ---- 2. certificate bundle"), s.index("# ---- 3. mode"))

    def test_every_prompt_loop_is_bounded(self):
        self.assertNotIn("while ($true)", pkg.INSTALL_PS1)
        self.assertNotRegex(pkg.INSTALL_PS1, r"while \(-not")


class BundledPythonTests(unittest.TestCase):
    """Package layout with the bundled Python, built from fake downloads (no network)."""

    def _fake_downloads(self, tmp):
        embed = Path(tmp, "python-embed.zip")
        with zipfile.ZipFile(embed, "w") as e:
            e.writestr("python.exe", b"MZ")
            e.writestr("python314.zip", b"stdlib")
            e.writestr("python314._pth", "python314.zip\r\n.\r\n#import site\r\n")
        wheel = Path(tmp, "demo_pkg-1.0-py3-none-any.whl")
        with zipfile.ZipFile(wheel, "w") as w:
            w.writestr("demo_pkg/__init__.py", "")
            w.writestr("demo_pkg-1.0.dist-info/METADATA", "Name: demo_pkg")
        return str(embed), [str(wheel)]

    def test_layout_and_search_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            embed, wheels = self._fake_downloads(tmp)
            with mock.patch.object(pkg, "fetch_embedded_python", return_value=embed), \
                    mock.patch.object(pkg, "fetch_wheels", return_value=wheels):
                out = _build(tmp, bundle_python=True)
            with zipfile.ZipFile(out) as z:
                names = set(z.namelist())
                pth = z.read("python/python314._pth").decode()
        self.assertTrue({"python/python.exe", "python/python314.zip", "python/SOURCE.txt",
                         "python/Lib/site-packages/demo_pkg/__init__.py"} <= names)
        self.assertEqual(pth.split("\r\n")[:5],
                         ["python314.zip", ".", "Lib\\site-packages", "..\\app", "import site"])

    def test_no_python_unless_asked(self):
        with tempfile.TemporaryDirectory() as tmp:
            with zipfile.ZipFile(_build(tmp)) as z:
                self.assertFalse(any(n.startswith("python/") for n in z.namelist()))

    def test_wrong_download_is_refused(self):
        class _Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(pkg.urllib.request, "urlopen", return_value=_Resp(b"tampered")):
            with self.assertRaisesRegex(SystemExit, "SHA256"):
                pkg.fetch_embedded_python(tmp)
            self.assertEqual(os.listdir(tmp), [])

    def test_bootstrap_prefers_bundled_python(self):
        bundled = pkg.BOOTSTRAP_PS1.index('python\\python.exe')
        self.assertLess(bundled, pkg.BOOTSTRAP_PS1.index("Get-Command $Python"))
        self.assertLess(bundled, pkg.BOOTSTRAP_PS1.index("pip install"))


class InstallerPitfallTests(unittest.TestCase):
    """PowerShell traps the parse check cannot see."""

    def test_no_validated_params_that_are_reassigned(self):
        # A [ValidateSet] parameter is validated on every later assignment too: assigning ""
        # or $null (value missing from device.env) throws and stops the installer.
        params = pkg.INSTALL_PS1.split("param(", 1)[1].split(")\n", 1)[0]
        for name in re.findall(r"\[Validate\w+\([^]]*\)\]\s*\[\w+\]\$(\w+)", params):
            body = pkg.INSTALL_PS1.split(")\n", 1)[1]
            self.assertNotRegex(body, rf"\${name}\s*=[^=]", f"${name} is validated and reassigned")


class LanguageTests(unittest.TestCase):
    """Every message exists in both languages, and every message the scripts use exists."""

    @staticmethod
    def _keys(block: str) -> set:
        return set(re.findall(r"^\s+(\w+)\s+=", block, re.MULTILINE))

    def test_same_keys_in_fi_and_en(self):
        fi = pkg.LANG_PS1.split("fi = @{", 1)[1].split("en = @{", 1)[0]
        en = pkg.LANG_PS1.split("en = @{", 1)[1].split("function T", 1)[0]
        self.assertEqual(self._keys(fi), self._keys(en))
        self.assertGreater(len(self._keys(fi)), 40)

    def test_used_keys_exist(self):
        fi = self._keys(pkg.LANG_PS1.split("fi = @{", 1)[1].split("en = @{", 1)[0])
        used = set()
        for content in GENERATED_PS1.values():
            used |= set(re.findall(r"\(T\s+[\"']([a-z_]+)[\"']", content))
        used |= {f"mode_{m}" for m in pkg.MODES}  # built as T "mode_$Mode"
        self.assertEqual(used - fi, set())

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
        # (confirmed against this repo's own setup.ps1). The package scripts are written
        # with a BOM (as in the package), so either works, but prefer pwsh to avoid that false-positive class entirely.
        cls.ps = shutil.which("pwsh") or shutil.which("powershell")
        if not cls.ps:
            raise unittest.SkipTest("no pwsh/powershell on PATH")
        cls.checker = str(Path(__file__).resolve().parent / "ps_syntax_check.ps1")

    def _assert_parses(self, name, content):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / name
            target.write_text(content, encoding="utf-8-sig")  # as in the package
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
        for f in sorted([*(REPO_ROOT / "demo").glob("*.ps1"), *(REPO_ROOT / "tests").glob("*.ps1")]):
            with self.subTest(name=f.name):
                self._assert_parses(f.name, f.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
