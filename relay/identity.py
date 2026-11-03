"""Locate this device's EFDI mTLS bundle and derive its org slot. No zenoh import.

A bundle directory holds `<prefix>-cert.pem`, `<prefix>-key.pem` and a CA root (normally
`efdi-ca-root.pem`). The org slot (write namespace) is, in order:
  1. GOAT_ORG
  2. the client certificate's CN (on EFDI the CN *is* the slot)
  3. the cert file prefix, when it looks like a 32-hex slot id

Used by goat_connect.py (runtime) and tools/make_relay_package.py (build machine, no zenoh).
"""
import glob
import os
import re
import ssl

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SLOT_RE = re.compile(r"^[0-9a-f]{32}$")
_CA_NAMES = ("efdi-ca-root.pem", "ca-root.pem", "ca-roots.pem")


def cert_dirs() -> list:
    """Directories searched for a bundle. GOAT_CERT_DIR, when set, is the only one."""
    if os.environ.get("GOAT_CERT_DIR"):
        return [os.environ["GOAT_CERT_DIR"]]
    return [os.path.join(REPO_ROOT, "certs"), "certs", "/certs"]


def find_bundle(d: str):
    """Return (cert, key, ca) from directory d, or (None, None, None)."""
    if not os.path.isdir(d):
        return None, None, None
    pairs = [(c, c[: -len("-cert.pem")] + "-key.pem") for c in sorted(glob.glob(os.path.join(d, "*-cert.pem")))]
    pairs = [(c, k) for c, k in pairs if os.path.isfile(k)]
    ca = next((os.path.join(d, n) for n in _CA_NAMES if os.path.isfile(os.path.join(d, n))), None)
    if ca is None:
        others = [f for f in sorted(os.listdir(d)) if f.endswith(".pem") and "cert" not in f and "key" not in f]
        ca = os.path.join(d, others[0]) if others else None
    if len(pairs) != 1 or ca is None:
        # zero or several identities: refuse to guess which one to present
        return None, None, None
    return pairs[0][0], pairs[0][1], ca


def resolve_bundle():
    """(cert, key, ca) from GOAT_CERT/GOAT_KEY/GOAT_CA, else the first cert dir holding one bundle."""
    explicit = (os.environ.get("GOAT_CERT"), os.environ.get("GOAT_KEY"), os.environ.get("GOAT_CA"))
    if all(explicit):
        return explicit
    for d in cert_dirs():
        found = find_bundle(d)
        if found[0]:
            return found
    return None, None, None


def cert_cn(cert_path: str) -> str:
    try:
        # CPython's PEM decoder; stdlib-only, avoids a `cryptography` dependency.
        subject = ssl._ssl._test_decode_cert(cert_path).get("subject", ())
    except (OSError, ssl.SSLError, AttributeError, ValueError):
        return ""
    return next((v for rdn in subject for k, v in rdn if k == "commonName"), "")


def org_for(cert_path) -> str:
    """The org slot for this bundle; "" when it cannot be determined."""
    env = os.environ.get("GOAT_ORG", "").strip()
    if env or not cert_path:
        return env
    cn = cert_cn(cert_path)
    if cn:
        return cn
    prefix = os.path.basename(cert_path)[: -len("-cert.pem")]
    return prefix if _SLOT_RE.match(prefix) else ""
