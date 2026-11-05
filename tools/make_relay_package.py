#!/usr/bin/env python3
"""Build a self-contained, self-installing TAK relay device package for a field device.

Windows (default): a ZIP with relay/ (unchanged, as app/), one mTLS cert bundle, the installer
from tools/field_package/ (install.cmd/.ps1, uninstall, run, bootstrap, lang), the bundled
Python and READMEs in Finnish and English.
Linux (--platform linux): a .tar.gz with the same app/ and certs/, the installer from
tools/field_package/linux/ (install.sh, uninstall.sh, run.sh, common.sh, lang.txt) and the
dependency wheels for x86_64 and aarch64. On the device: tar -xzf, ./install.sh. On the device: unzip, double-click install.cmd. The installer asks for the
language (fi/en), then the mode (direct / local network / TAK Server) and the mode's details,
installs the dependencies, registers automatic start and starts the relay. Anything given here
(--lang, --mode, --tak-server ...) is written to device.env and not asked again.

Usage:
    python tools/make_relay_package.py --system field-relay-01
    python tools/make_relay_package.py --system field-relay-01 --lang en --mode direct
    python tools/make_relay_package.py --system field-relay-02 --platform linux
    python tools/make_relay_package.py --system hq-relay --mode server --tak-server tak.example:8089 \
        --tak-p12 relay.p12 --tak-trust-p12 truststore-root.p12      # password is asked at install

Each device gets its own package because GATEWAY_SYSTEM (used for the
heartbeat / portal display name) must be unique per device and must match
what's registered in the portal (see docs/en/field-package.md) -- register the name
before dropping the package, or the heartbeat will show up unregistered.
All devices reuse the same vendor cert (Zenoh identity is per-org, not
per-device); only GATEWAY_SYSTEM and the output ports vary.
"""
import argparse
import glob
import hashlib
import io
import os
import subprocess
import sys
import tarfile
import time
import urllib.request
import zipfile

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)

sys.path.insert(0, os.path.join(REPO_ROOT, "relay"))
import identity  # noqa: E402  (stdlib only: the build machine needs no zenoh)

# tak_gateway.py's own sys.path.insert(dirname(__file__)) means every sibling
# module just needs to sit next to it in the package -- no install step for
# our own code, only the one third-party dependency (eclipse-zenoh).
APP_FILES = [
    "tak_gateway.py",
    "backbone_cot.py",
    "cot_guard.py",
    "doctor.py",
    "gateway_core.py",
    "goat_connect.py",
    "heartbeat.py",
    "identity.py",
    "stream_view.py",
    "status_page.py",
    "symbology.py",
    "tak_links.py",
    "video_relay.py",
]

TEMPLATE_DIR = os.path.join(SCRIPT_DIR, "field_package")


def _template(name: str) -> str:
    with open(os.path.join(TEMPLATE_DIR, name), encoding="utf-8") as f:
        return f.read()


# PowerShell scripts of the package. Written with a UTF-8 BOM so Windows PowerShell 5.1 reads
# the Finnish letters in lang.ps1 correctly.
PS1_FILES = ("lang.ps1", "bootstrap.ps1", "run.ps1", "install.ps1", "uninstall.ps1")
LANG_PS1, BOOTSTRAP_PS1, RUN_PS1, INSTALL_PS1, UNINSTALL_PS1 = (_template(n) for n in PS1_FILES)
README_FI, README_EN = _template("README.fi.md"), _template("README.en.md")
MODES = ("direct", "multicast", "server")
PLATFORMS = ("windows", "linux")

# Linux installer (tools/field_package/linux/). The .sh files except common.sh are executable.
LINUX_FILES = ("common.sh", "install.sh", "run.sh", "uninstall.sh", "lang.txt")
LINUX_TEMPLATES = {n: _template(os.path.join("linux", n)) for n in LINUX_FILES}
LINUX_README_FI, LINUX_README_EN = _template("linux/README.fi.md"), _template("linux/README.en.md")
# Wheels for these machines and Python versions: eclipse-zenoh and cryptography are abi3, cffi is
# per Python version. manylinux needs glibc 2.17 (zenoh) / 2.28 (cryptography).
LINUX_ARCHES = ("x86_64", "aarch64")
LINUX_PYTHONS = ("3.10", "3.11", "3.12", "3.13")

# Bundled Python (Windows amd64): the device needs no Python and no network at install.
# The embeddable zip is pinned to the SHA256 python.org publishes for it; the wheels come from
# PyPI over HTTPS (pip checks the index hashes). Both are cached in dist/cache/.
EMBED_PYTHON = {
    "version": "3.14.10",
    "url": "https://www.python.org/ftp/python/3.14.10/python-3.14.10-embed-amd64.zip",
    "sha256": "90905e64a840557d8c1bc4f5b74db3d7ee85e3ffb217611cac1c7813acea4159",
}
FIELD_REQUIREMENTS = ("eclipse-zenoh==1.9.0", "cryptography==46.0.3")
CACHE_DIR = os.path.join(REPO_ROOT, "dist", "cache")


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch_embedded_python(cache: str = CACHE_DIR) -> str:
    """Path to the pinned embeddable Python zip, downloaded once and checked against its SHA256."""
    os.makedirs(cache, exist_ok=True)
    path = os.path.join(cache, os.path.basename(EMBED_PYTHON["url"]))
    if not os.path.isfile(path) or _sha256(path) != EMBED_PYTHON["sha256"]:
        print(f"downloading {EMBED_PYTHON['url']}")
        tmp = path + ".part"
        with urllib.request.urlopen(EMBED_PYTHON["url"], timeout=120) as r, open(tmp, "wb") as f:
            while chunk := r.read(1 << 20):
                f.write(chunk)
        got = _sha256(tmp)
        if got != EMBED_PYTHON["sha256"]:
            os.remove(tmp)
            raise SystemExit(f"ERROR: {EMBED_PYTHON['url']} has SHA256 {got}, expected {EMBED_PYTHON['sha256']}")
        os.replace(tmp, path)
    return path


def fetch_wheels(cache: str = CACHE_DIR) -> list:
    """Windows amd64 wheels of FIELD_REQUIREMENTS (and their dependencies) for the bundled Python."""
    minor = ".".join(EMBED_PYTHON["version"].split(".")[:2])
    key = hashlib.sha256(" ".join(FIELD_REQUIREMENTS).encode()).hexdigest()[:12]
    d = os.path.join(cache, f"wheels-win_amd64-py{minor}-{key}")
    done = os.path.join(d, ".complete")
    if not os.path.isfile(done):
        os.makedirs(d, exist_ok=True)
        subprocess.run([sys.executable, "-m", "pip", "download", "--quiet", "--only-binary=:all:",
                        "--platform", "win_amd64", "--python-version", minor, "--implementation", "cp",
                        "--dest", d, *FIELD_REQUIREMENTS], check=True)
        open(done, "w").close()
    wheels = sorted(glob.glob(os.path.join(d, "*.whl")))
    if not wheels:
        raise SystemExit(f"ERROR: no wheels in {d}")
    return wheels


def fetch_linux_wheels(cache: str = CACHE_DIR) -> dict:
    """{arch: [wheel paths]} of FIELD_REQUIREMENTS for LINUX_ARCHES and LINUX_PYTHONS (pip checks
    the index hashes; the wheels are cached in dist/cache/)."""
    key = hashlib.sha256(" ".join(FIELD_REQUIREMENTS + LINUX_PYTHONS).encode()).hexdigest()[:12]
    out = {}
    for arch in LINUX_ARCHES:
        d = os.path.join(cache, f"wheels-linux_{arch}-{key}")
        done = os.path.join(d, ".complete")
        if not os.path.isfile(done):
            os.makedirs(d, exist_ok=True)
            platforms = [a for p in (f"manylinux_2_28_{arch}", f"manylinux_2_17_{arch}", f"manylinux2014_{arch}")
                         for a in ("--platform", p)]
            for py in LINUX_PYTHONS:
                subprocess.run([sys.executable, "-m", "pip", "download", "--quiet", "--only-binary=:all:",
                                *platforms, "--python-version", py, "--implementation", "cp",
                                "--dest", d, *FIELD_REQUIREMENTS], check=True)
            open(done, "w").close()
        out[arch] = sorted(glob.glob(os.path.join(d, "*.whl")))
        if not out[arch]:
            raise SystemExit(f"ERROR: no wheels in {d}")
    return out


def add_bundled_python(z: zipfile.ZipFile, embed_zip: str, wheels: list) -> None:
    """python/ = embeddable Python + the wheels unpacked into python/Lib/site-packages."""
    pth = None
    with zipfile.ZipFile(embed_zip) as e:
        for info in e.infolist():
            if info.filename.endswith("._pth"):
                pth = info.filename
                continue
            z.writestr(f"python/{info.filename}", e.read(info))
    if pth is None:
        raise SystemExit(f"ERROR: no ._pth file in {embed_zip}")
    stdlib = pth[: -len("._pth")] + ".zip"
    # sys.path of the bundled Python: stdlib, its folder, the wheels and the relay modules.
    z.writestr(f"python/{pth}", f"{stdlib}\r\n.\r\nLib\\site-packages\r\n..\\app\r\nimport site\r\n")
    for whl in wheels:
        with zipfile.ZipFile(whl) as w:
            for info in w.infolist():
                if not info.is_dir():
                    z.writestr(f"python/Lib/site-packages/{info.filename}", w.read(info))
    z.writestr("python/SOURCE.txt",
               f"Python {EMBED_PYTHON['version']} embeddable amd64 from {EMBED_PYTHON['url']}\r\n"
               f"SHA256 {EMBED_PYTHON['sha256']}\r\n"
               + "".join(f"{os.path.basename(w)} SHA256 {_sha256(w)}\r\n" for w in wheels))

INSTALL_CMD = r"""@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
echo.
pause
"""

UNINSTALL_CMD = r"""@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0uninstall.ps1" %*
echo.
pause
"""

DEVICE_ENV_TMPL = """\
# Device settings for the TAK relay. {runner} reads this at every start.
# Asetukset: README.fi.md. Settings: README.en.md. Full list: docs/en/relay.md in the repository.

# Installer choices. A commented line is asked by {installer}.
{lang_line}
{mode_line}

GOAT_CERT_DIR={cert_dir}
# Slot: from the certificate when not set. Router: from {notes} when not set.
{org_line}
{router_line}

# Name in the portal and in the heartbeat. Must be registered in the portal beforehand.
{system_line}
GATEWAY_HTTP_PORT=8088

# Mode direct: CoT by UDP to the TAK app (default 6969, WinTAK 4242). Another machine: its IP.
TAK_HOST={tak_host}
TAK_UDP_PORT={tak_udp_port}
# TCP stream for ATAK/WinTAK (all modes).
TAK_PORT={tak_port}

# Mode server: TAK Server address and its .p12 files (paths relative to this folder).
{server_lines}

# 1 = publish your own devices' position (friendly PLI) to the backbone.
TAK_INGEST={tak_ingest}
# UDP port for the TAK app's own position (its UDP output).
TAK_UDP_IN_PORT={tak_udp_in_port}
# Only these device uids may publish (comma-separated). Empty: only TAK apps on this machine.
# Required in mode multicast.
{uids_line}

# Convert every recognised position format on the backbone (all vendors).
GATEWAY_INGEST_ALL=1
"""


def relay_version() -> str:
    """__version__ of relay/tak_gateway.py, read without importing it (it needs zenoh)."""
    with open(os.path.join(REPO_ROOT, "relay", "tak_gateway.py"), encoding="utf-8") as f:
        for ln in f:
            if ln.startswith("__version__"):
                return ln.split("=", 1)[1].strip().strip('"\'')
    raise SystemExit("ERROR: no __version__ in relay/tak_gateway.py")


def build_package(system, cert_dir, out: str, tak_host: str, tak_udp_port: int,
                  tak_port: int, tak_ingest: bool, tak_udp_in_port: int, router: str = None,
                  lang: str = None, mode: str = None, tak_server: str = None, tak_p12: str = None,
                  tak_trust_p12: str = None, ingest_uids: str = None, bundle_python: bool = False,
                  cache: str = CACHE_DIR, template: bool = False, platform: str = "windows") -> None:
    """template=True: no certificate bundle and no device name; the installer asks for both.
    platform: "windows" (ZIP; bundle_python = embeddable Python + wheels) or "linux" (.tar.gz;
    bundle_python = wheels for LINUX_ARCHES)."""
    if platform not in PLATFORMS:
        raise SystemExit(f"ERROR: --platform must be one of {', '.join(PLATFORMS)}, not {platform!r}")
    linux = platform == "linux"
    installer = "install.sh" if linux else "install.cmd"
    cert = key = ca = org = None
    if not template:
        cert, key, ca = identity.find_bundle(cert_dir)
        if not (cert and key and ca):
            raise SystemExit(f"ERROR: need exactly one <prefix>-cert.pem/-key.pem pair + a CA .pem in {cert_dir!r}")
        org = identity.org_for(cert)
        if not org:
            raise SystemExit(f"ERROR: cannot read the org slot from {cert}; set GOAT_ORG=<slot id>")
        if not system:
            raise SystemExit("ERROR: --system is required (or build a --template)")
    if lang not in (None, "fi", "en"):
        raise SystemExit(f"ERROR: --lang must be fi or en, not {lang!r}")
    if mode not in (None, *MODES):
        raise SystemExit(f"ERROR: --mode must be one of {', '.join(MODES)}, not {mode!r}")
    for f in (tak_p12, tak_trust_p12):
        if f and not os.path.isfile(f):
            raise SystemExit(f"ERROR: {f} not found")
    if not template:
        router = router or identity.router_for(cert)
        if not router:
            raise SystemExit("ERROR: no fabric router: the bundle has no NOTES.md with 'Router endpoint:'; "
                             "pass --router tls/<router>:<port> from your onboarding bundle")

    def line(key: str, value) -> str:
        return f"{key}={value}" if value else f"# {key}="

    tak_dir = "certs/tak/" if linux else "certs\\tak\\"
    server_lines = "\n".join([
        line("TAK_SERVER", tak_server),
        line("TAK_SERVER_P12", tak_p12 and f"{tak_dir}{os.path.basename(tak_p12)}"),
        line("TAK_SERVER_TRUST_P12", tak_trust_p12 and f"{tak_dir}{os.path.basename(tak_trust_p12)}"),
        f"# TAK_SERVER_P12_PASSWORD=   (asked by {installer}; never passed on the command line)",
        "# TAK_SERVER_VERIFY_HOSTNAME=0   (only if the server certificate does not name its address)",
    ])
    device_env = DEVICE_ENV_TMPL.format(
        runner="run.sh" if linux else "run.ps1", installer=installer,
        cert_dir="./certs" if linux else ".\\certs", notes="certs/NOTES.md" if linux else "certs\\NOTES.md",
        lang_line=line("RELAY_LANG", lang), mode_line=line("TAK_MODE", mode),
        org_line=line("GOAT_ORG", org), router_line=line("GOAT_ROUTER", router),
        system_line=line("GATEWAY_SYSTEM", system), tak_host=tak_host, tak_udp_port=tak_udp_port,
        tak_port=tak_port, server_lines=server_lines, tak_ingest="1" if tak_ingest else "0",
        tak_udp_in_port=tak_udp_in_port, uids_line=line("TAK_INGEST_UIDS", ingest_uids))

    # (name in the package, content, mode). The mode matters in the Linux .tar.gz only: the key,
    # the TAK Server .p12 files and device.env are 0600, the installer scripts 0755.
    files = []

    def add(name: str, content, mode: int = 0o644) -> None:
        files.append((name, content if isinstance(content, bytes) else content.encode("utf-8"), mode))

    def read(path: str) -> bytes:
        with open(path, "rb") as fh:
            return fh.read()

    for name in APP_FILES:
        add(f"app/{name}", read(os.path.join(REPO_ROOT, "relay", name)))
    if template:
        add("certs/README.txt", f"Put your EFDI bundle here, or let {installer} copy it.\r\n"
                                f"Laita EFDI-varmennepaketti tähän, tai anna {installer}:n kopioida se.\r\n")
    else:
        add(f"certs/{os.path.basename(cert)}", read(cert))
        add(f"certs/{os.path.basename(key)}", read(key), 0o600)
        add("certs/efdi-ca-root.pem", read(ca))
        notes = os.path.join(os.path.dirname(cert), "NOTES.md")
        if os.path.isfile(notes):
            add("certs/NOTES.md", read(notes))
    for f in (tak_p12, tak_trust_p12):
        if f:
            add(f"certs/tak/{os.path.basename(f)}", read(f), 0o600)
    add("device.env", device_env, 0o600)
    fmt = dict(system=system or "tak-relay", tak_udp_port=tak_udp_port, tak_port=tak_port)
    if linux:
        for name in LINUX_FILES:
            add(name, LINUX_TEMPLATES[name].replace("\r\n", "\n"),
                0o755 if name.endswith(".sh") and name != "common.sh" else 0o644)
        add("README.fi.md", LINUX_README_FI.format(**fmt))
        add("README.en.md", LINUX_README_EN.format(**fmt))
    else:
        for name, content in zip(PS1_FILES, (LANG_PS1, BOOTSTRAP_PS1, RUN_PS1, INSTALL_PS1, UNINSTALL_PS1)):
            # UTF-8 BOM and CRLF: Windows PowerShell 5.1 reads the Finnish letters correctly.
            add(name, "﻿" + content.replace("\r\n", "\n").replace("\n", "\r\n"))
        add("install.cmd", INSTALL_CMD)
        add("uninstall.cmd", UNINSTALL_CMD)
        add("README.fi.md", README_FI.format(**fmt))
        add("README.en.md", README_EN.format(**fmt))

    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    if linux:
        if bundle_python:
            for arch, wheels in fetch_linux_wheels(cache).items():
                for whl in wheels:
                    add(f"wheels/{arch}/{os.path.basename(whl)}", read(whl))
                add(f"wheels/{arch}/SOURCE.txt",
                    "".join(f"{os.path.basename(w)} SHA256 {_sha256(w)}\n" for w in wheels))
        _write_tar(out, files)
    else:
        if bundle_python:
            embed_zip, wheels = fetch_embedded_python(cache), fetch_wheels(cache)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for name, content, _ in files:
                z.writestr(name, content)
            if bundle_python:
                add_bundled_python(z, embed_zip, wheels)
        with open(out, "wb") as fh:
            fh.write(buf.getvalue())
    if not bundle_python:
        deps = "device"
    else:
        deps = ("wheels " + ", ".join(LINUX_ARCHES)) if linux else ("bundled " + EMBED_PYTHON["version"])
    print(f"wrote {out} ({os.path.getsize(out)} bytes): platform={platform} system={system!r} "
          f"lang={lang or 'ask'} mode={mode or 'ask'} python={deps} tak_host={tak_host} "
          f"tak_udp_port={tak_udp_port} tak_port={tak_port}")
    if template:
        print(f"Template: no certificate and no device name inside; {installer} asks for both.")
        return
    print("Cert bundled from:", cert, key, ca)
    print(f"Before shipping this to the device, register its heartbeat topic: "
          f"python tools/register_portal_topics.py --add-system {system} --apply")


def _write_tar(out: str, files: list) -> None:
    """The Linux package: one top-level folder (so "tar -xzf" does not spill files into the current
    directory), with each file's mode. certs/ and its subfolders are 0700."""
    top = os.path.basename(out).removesuffix(".tar.gz").removesuffix(".tgz")
    now = time.time()
    dirs = set()
    for name, _, _ in files:
        parts = name.split("/")[:-1]
        dirs.update("/".join(parts[:i]) for i in range(1, len(parts) + 1))
    with tarfile.open(out, "w:gz") as t:
        for d in [""] + sorted(dirs):
            info = tarfile.TarInfo(f"{top}/{d}".rstrip("/"))
            info.type, info.mtime = tarfile.DIRTYPE, now
            info.mode = 0o700 if d == "certs" or d.startswith("certs/") else 0o755
            t.addfile(info)
        for name, content, mode in files:
            info = tarfile.TarInfo(f"{top}/{name}")
            info.size, info.mode, info.mtime = len(content), mode, now
            t.addfile(info, io.BytesIO(content))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--system", help="unique device/system name (GATEWAY_SYSTEM, must be registered in the "
                                     "portal, and the zip's default filename). Required unless --template")
    p.add_argument("--template", action="store_true",
                   help="no certificate and no device name (safe to publish); the installer asks for both")
    p.add_argument("--platform", choices=PLATFORMS, default="windows",
                   help="windows: ZIP with install.cmd (default); linux: .tar.gz with install.sh")
    p.add_argument("--cert-dir", default=os.path.join(REPO_ROOT, "certs"),
                   help="dir with <org>-cert.pem/-key.pem + CA root (default: ./certs)")
    p.add_argument("--out", default=None, help="output path (default: dist/<system>-tak-relay.zip, or -linux.tar.gz)")
    p.add_argument("--lang", choices=("fi", "en"), help="installer language (default: asked at install)")
    p.add_argument("--mode", choices=MODES, help="TAK_MODE (default: asked at install)")
    p.add_argument("--tak-host", default="127.0.0.1", help="mode direct: where the TAK app listens (default: same device)")
    p.add_argument("--tak-udp-port", type=int, default=6969, help="mode direct: TAK app CoT UDP input port (default 6969)")
    p.add_argument("--tak-port", type=int, default=8087, help="TCP stream port for ATAK/WinTAK-style input")
    p.add_argument("--tak-udp-in-port", type=int, default=6971, help="UDP port this relay listens on for the TAK app's PLI")
    p.add_argument("--no-ingest", action="store_true", help="don't publish the device's own PLI to the backbone")
    p.add_argument("--ingest-uids", help="TAK_INGEST_UIDS: device uids allowed to publish (comma-separated)")
    p.add_argument("--tak-server", help="mode server: TAK Server host[:port]")
    p.add_argument("--tak-p12", help="mode server: relay client certificate .p12 (copied to certs/tak/)")
    p.add_argument("--tak-trust-p12", help="mode server: TAK Server truststore .p12 (copied to certs/tak/)")
    p.add_argument("--router", default=None, help="Zenoh router endpoint (default: the bundle's NOTES.md)")
    p.add_argument("--no-bundled-python", action="store_true",
                   help="windows: do not include Python; the device then needs Python 3.10+ and network at install")
    p.add_argument("--no-bundled-wheels", action="store_true",
                   help="linux: do not include the dependency wheels; the device then needs network at install")
    args = p.parse_args()

    if not args.template and not args.system:
        p.error("--system is required unless --template")
    linux = args.platform == "linux"
    if args.template:
        name = f"efdi-tak-relay-{relay_version()}-" + ("linux" if linux else "windows-x64")
    else:
        name = f"{args.system}-tak-relay" + ("-linux" if linux else "")
    out = args.out or os.path.join(REPO_ROOT, "dist", name + (".tar.gz" if linux else ".zip"))
    bundle = not (args.no_bundled_wheels if linux else args.no_bundled_python)
    build_package(args.system, args.cert_dir, out, args.tak_host, args.tak_udp_port,
                  args.tak_port, not args.no_ingest, args.tak_udp_in_port, args.router,
                  lang=args.lang, mode=args.mode, tak_server=args.tak_server, tak_p12=args.tak_p12,
                  tak_trust_p12=args.tak_trust_p12, ingest_uids=args.ingest_uids,
                  bundle_python=bundle, template=args.template, platform=args.platform)


if __name__ == "__main__":
    main()
