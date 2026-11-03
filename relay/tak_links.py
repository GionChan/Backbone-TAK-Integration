"""TAK-side link settings (mode, UDP targets, multicast, TAK Server) and the TAK Server TLS context.

Stdlib only, so doctor.py can use it without zenoh. Reading .p12 files needs `cryptography`
(imported only when a .p12 is configured).

TAK_MODE picks one of three set-ups (docs/en/modes.md); single variables still override:
  direct     (default) CoT by UDP to TAK_UDP_TARGETS + TCP server on TAK_PORT. TAK needs one input port.
  multicast  CoT to the TAK SA multicast group (239.2.3.1:6969) + TCP server. TAK needs no settings.
             Everyone on the LAN segment sees the data. PLI heard on the group is published only
             for uids in TAK_INGEST_UIDS.
  server     CoT to a TAK Server (TAK_SERVER required). Local UDP/TCP outputs are off unless
             TAK_LOCAL_OUTPUTS=1, so devices on the server do not get every marker twice.

Multicast env: TAK_MULTICAST_GROUP (239.2.3.1:6969), TAK_MULTICAST_IF (IPv4 address of the LAN
interface; default: the OS picks), TAK_MULTICAST_TTL (1 = stays on the segment).

TAK Server env:
  TAK_SERVER                 host[:port]  (port 8089 if omitted)
  TAK_SERVER_TLS             1/0 (default 1, except port 8087 -> 0)
  TAK_SERVER_P12             client certificate .p12 issued by the TAK Server
  TAK_SERVER_P12_PASSWORD
  TAK_SERVER_TRUST_P12       truststore .p12 (the TAK Server CA)
  TAK_SERVER_TRUST_PASSWORD  (default: TAK_SERVER_P12_PASSWORD)
  TAK_SERVER_CERT/KEY/CA     PEM files instead of .p12
  TAK_SERVER_VERIFY_HOSTNAME 1/0 (default 1)
"""
import os
import shutil
import ssl
import tempfile


MODES = ("direct", "multicast", "server")
SA_GROUP = "239.2.3.1:6969"


class ConfigError(ValueError):
    """A TAK_MODE set-up that cannot work; the message says what to set."""


def mode() -> str:
    m = os.environ.get("TAK_MODE", "direct").strip().lower() or "direct"
    if m not in MODES:
        raise ConfigError(f"TAK_MODE={m!r}: use one of {', '.join(MODES)}")
    return m


def multicast_group() -> tuple:
    host, _, port = os.environ.get("TAK_MULTICAST_GROUP", SA_GROUP).rpartition(":")
    return host, int(port)


def multicast_output() -> dict:
    host, port = multicast_group()
    return {"type": "udp", "host": host, "port": port, "multicast": True,
            "ttl": int(os.environ.get("TAK_MULTICAST_TTL", "1")),
            "iface": os.environ.get("TAK_MULTICAST_IF", "")}


def outputs(m: str = None) -> list:
    """Output configs for the mode. Raises ConfigError for a set-up that cannot work."""
    m = m or mode()
    tcp = {"type": "tcp_server", "port": int(os.environ.get("TAK_PORT", "8087"))}
    server = tak_server()
    if m == "direct":
        out = udp_targets() + [tcp]
    elif m == "multicast":
        out = [multicast_output(), tcp]
    else:
        if not server:
            raise ConfigError("TAK_MODE=server needs TAK_SERVER=<host[:port]> (and its .p12 files)")
        local = os.environ.get("TAK_LOCAL_OUTPUTS", "0") == "1"
        out = udp_targets() + [tcp] if local else []
    if server:
        out.append(server)
    return out


def default_ingest_from(m: str = None) -> str:
    """Which TAK links may publish PLI when TAK_INGEST_FROM is not set."""
    return "local,lan" if (m or mode()) == "multicast" else "local"


def udp_targets() -> list:
    """[{"type": "udp", "host", "port"}] from TAK_UDP_TARGETS, else TAK_HOST:TAK_UDP_PORT."""
    targets = os.environ.get("TAK_UDP_TARGETS") or (
        f'{os.environ.get("TAK_HOST", "127.0.0.1")}:{os.environ.get("TAK_UDP_PORT", "6969")}')
    out = []
    for t in filter(None, (x.strip() for x in targets.split(","))):
        host, _, port = t.rpartition(":")
        out.append({"type": "udp", "host": host, "port": int(port)})
    return out


def tak_server() -> dict:
    """tcp_client output config for TAK_SERVER, or None when it is not set."""
    target = os.environ.get("TAK_SERVER", "").strip()
    if not target:
        return None
    host, sep, port = target.rpartition(":")
    if not sep:
        host, port = target, "8089"
    cfg = {"type": "tcp_client", "host": host, "port": int(port)}
    if os.environ.get("TAK_SERVER_TLS", "0" if port == "8087" else "1") != "1":
        return cfg
    env = os.environ.get
    tls = {
        "p12": env("TAK_SERVER_P12"),
        "p12_password": env("TAK_SERVER_P12_PASSWORD"),
        "trust_p12": env("TAK_SERVER_TRUST_P12"),
        "trust_password": env("TAK_SERVER_TRUST_PASSWORD") or env("TAK_SERVER_P12_PASSWORD"),
        "cert": env("TAK_SERVER_CERT"),
        "key": env("TAK_SERVER_KEY"),
        "ca": env("TAK_SERVER_CA"),
    }
    cfg["tls"] = {k: v for k, v in tls.items() if v}
    cfg["tls"]["verify_hostname"] = env("TAK_SERVER_VERIFY_HOSTNAME", "1") == "1"
    return cfg


def _pkcs12(path: str, password):
    try:
        from cryptography.hazmat.primitives.serialization import pkcs12
    except ImportError as exc:
        raise RuntimeError(
            f"{path}: .p12 files need `pip install cryptography`, or convert to PEM "
            "(openssl pkcs12 -in x.p12 -out x.pem -nodes) and use TAK_SERVER_CERT/KEY/CA") from exc
    with open(path, "rb") as f:
        data = f.read()
    try:
        return pkcs12.load_key_and_certificates(data, password.encode() if password else None)
    except ValueError as exc:
        raise RuntimeError(f"{path}: cannot open .p12 (wrong password?)") from exc


def _pem(cert) -> str:
    from cryptography.hazmat.primitives.serialization import Encoding
    return cert.public_bytes(Encoding.PEM).decode("ascii")


def _load_p12_chain(ctx: ssl.SSLContext, path: str, password) -> None:
    from cryptography.hazmat.primitives.serialization import (BestAvailableEncryption, Encoding,
                                                              PrivateFormat)
    key, cert, extra = _pkcs12(path, password)
    if key is None or cert is None:
        raise RuntimeError(f"{path}: no client certificate and key inside")
    # ssl only loads chains from files. The key is written encrypted with a one-off passphrase
    # and the directory is removed straight after loading.
    secret = os.urandom(24).hex().encode()
    d = tempfile.mkdtemp(prefix="tak-p12-")
    try:
        cert_file, key_file = os.path.join(d, "c.pem"), os.path.join(d, "k.pem")
        with open(cert_file, "w", encoding="ascii") as f:
            f.write(_pem(cert) + "".join(_pem(c) for c in extra or ()))
        with open(key_file, "wb") as f:
            f.write(key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, BestAvailableEncryption(secret)))
        ctx.load_cert_chain(cert_file, key_file, password=secret)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def ssl_context(tls: dict) -> ssl.SSLContext:
    """Client TLS context for a TAK Server link (PEM or .p12). Raises RuntimeError/OSError/SSLError."""
    ctx = ssl.create_default_context(cafile=tls.get("ca"))
    if tls.get("trust_p12"):
        key, cert, extra = _pkcs12(tls["trust_p12"], tls.get("trust_password"))
        certs = [c for c in [cert, *(extra or ())] if c is not None]
        if not certs:
            raise RuntimeError(f"{tls['trust_p12']}: no CA certificate inside")
        ctx.load_verify_locations(cadata="".join(_pem(c) for c in certs))
    if tls.get("p12"):
        _load_p12_chain(ctx, tls["p12"], tls.get("p12_password"))
    elif tls.get("cert"):
        ctx.load_cert_chain(tls["cert"], tls.get("key"))
    if not tls.get("verify_hostname", True):
        ctx.check_hostname = False
    return ctx
