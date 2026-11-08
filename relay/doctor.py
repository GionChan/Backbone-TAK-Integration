#!/usr/bin/env python3
"""Preflight for the TAK relay: says what is wrong and how to fix it.

    python relay/doctor.py                              (native)
    docker compose exec tak-relay python3 relay/doctor.py
    .\\run.ps1 -CheckOnly                                (field package)

Reads the same env vars as the relay. Exit code 0 = no failures. Never writes to the fabric.
"""
import json
import os
import shutil
import socket
import ssl
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import identity  # noqa: E402
import tak_links  # noqa: E402

RESULTS = []


def report(status: str, what: str, detail: str = "", fix: str = "") -> None:
    RESULTS.append(status)
    print(f"[{status:^4}] {what}" + (f": {detail}" if detail else ""))
    if fix and status in ("FAIL", "WARN"):
        print(f"       -> {fix}")


def _connect(host: str, port: int, timeout: float = 5.0):
    """(ok, detail) for a TCP connection; resolves the name first so DNS errors are named."""
    try:
        addr = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)[0][4]
    except socket.gaierror as exc:
        return False, f"name {host} does not resolve ({exc.strerror})"
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, f"{addr[0]}:{port} reachable"
    except OSError as exc:
        return False, f"{addr[0]}:{port} not reachable ({exc})"


def _split(endpoint: str):
    rest = endpoint.split("/", 1)[-1]
    host, _, port = rest.rpartition(":")
    return host, int(port)


def check_python() -> None:
    v = sys.version_info
    status = "OK" if v >= (3, 10) else ("WARN" if v >= (3, 9) else "FAIL")
    report(status, "python", f"{v.major}.{v.minor}.{v.micro}", "Python 3.10+ recommended (tested on 3.12)")


def check_zenoh() -> None:
    try:
        from importlib.metadata import version
        ver = version("eclipse-zenoh")
        __import__("zenoh")
    except Exception as exc:  # noqa: BLE001
        report("FAIL", "eclipse-zenoh", f"not importable ({exc.__class__.__name__})",
               "pip install -r relay/requirements.txt")
        return
    report("OK" if ver == "1.9.0" else "WARN", "eclipse-zenoh", ver,
           "the fabric is tested with 1.9.0: pip install eclipse-zenoh==1.9.0")


def check_identity():
    cert, key, ca = identity.resolve_bundle()
    if not cert:
        where = ", ".join(identity.cert_dirs())
        downloads = os.path.join(os.path.expanduser("~"), "Downloads")
        packed = [f for f in (os.listdir(downloads) if os.path.isdir(downloads) else [])
                  if f.startswith("efdi-onboarding") and f.endswith((".zip", ".tar.gz"))]
        fix = (f"unpack {packed[0]} in Downloads, or copy it into certs/" if packed else
               "copy your EFDI bundle (<slot>-cert.pem, <slot>-key.pem, efdi-ca-root.pem) into certs/")
        if len(identity.downloaded_bundle_dirs()) > 1:
            fix = "several efdi-onboarding-* bundles in Downloads: set GOAT_CERT_DIR to the right one"
        report("WARN", "certificate bundle", f"none found ({where}); relay runs offline on the local router", fix)
        return None
    report("OK", "certificate bundle", os.path.dirname(os.path.abspath(cert)))
    org = identity.org_for(cert)
    report("OK" if org else "FAIL", "org slot", org or "cannot be read from the certificate",
           "set GOAT_ORG=<slot id>")
    try:
        not_after = ssl._ssl._test_decode_cert(cert)["notAfter"]
        days = (ssl.cert_time_to_seconds(not_after) - time.time()) / 86400
        status = "FAIL" if days < 0 else ("WARN" if days < 14 else "OK")
        report(status, "certificate validity", f"expires {not_after} ({days:.0f} days)",
               "get a new bundle from the EFDI portal")
    except (KeyError, ValueError, OSError, ssl.SSLError, AttributeError):
        report("WARN", "certificate validity", "cannot read the expiry date")
    try:
        with open(key, "rb"):
            pass
        report("OK", "private key", "readable")
    except OSError as exc:
        report("FAIL", "private key", str(exc), "on Linux/Docker: chmod 640 and give group 10001 read")
    return cert


def check_netbird() -> None:
    exe = shutil.which("netbird")
    if not exe:
        report("INFO", "netbird", "CLI not found here (normal inside Docker); check it on the host")
        return
    try:
        out = subprocess.run([exe, "status"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.TimeoutExpired) as exc:
        report("WARN", "netbird", f"status failed ({exc})")
        return
    for part in ("Management", "Signal"):
        line = next((ln for ln in out.splitlines() if ln.strip().startswith(part + ":")), "")
        ok = "Connected" in line and "Disconnected" not in line
        report("OK" if ok else "FAIL", f"netbird {part.lower()}", line.split(":", 1)[-1].strip() or "unknown",
               "netbird up (with your setup key); the router resolves only inside the mesh")


def check_router(cert) -> None:
    if cert:
        endpoint = identity.router_for(cert)
        if not endpoint:
            report("FAIL", "fabric router", "not known: no GOAT_ROUTER and no 'Router endpoint:' in the bundle's NOTES.md",
                   "set GOAT_ROUTER=tls/<router>:<port> from your onboarding bundle")
            return
        ok, detail = _connect(*_split(endpoint))
        report("OK" if ok else "FAIL", "fabric router", f"{endpoint}: {detail}",
               "check netbird; in Docker Desktop set EFDI_ROUTER_HOST and EFDI_ROUTER_IP (nslookup the router on the host)")
    else:
        endpoint = os.environ.get("GOAT_LOCAL_ROUTER") or "tcp/localhost:7447"
        ok, detail = _connect(*_split(endpoint))
        report("OK" if ok else "WARN", "local router", f"{endpoint}: {detail}",
               "python demo/local_router.py, or docker compose --profile demo up -d zenoh-router")


def check_running_relay() -> bool:
    port = int(os.environ.get("GATEWAY_HTTP_PORT", "8088"))
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/status", timeout=3) as r:
            st = json.load(r)
    except (OSError, ValueError):
        return False
    reasons = "; ".join(st.get("reasons") or [])
    report("OK" if st.get("healthy") else "FAIL", "running relay", f"http://127.0.0.1:{port}/ "
           + ("healthy" if st.get("healthy") else reasons), "see docs/en/troubleshooting.md for each reason")
    return True


def check_ports(m) -> None:
    ports = [("tcp", int(os.environ.get("GATEWAY_HTTP_PORT", "8088")), "HTTP status")]
    if m and any(o["type"] == "tcp_server" for o in tak_links.outputs(m)):
        ports.insert(0, ("tcp", int(os.environ.get("TAK_PORT", "8087")), "TAK TCP stream"))
    if int(os.environ.get("TAK_UDP_IN_PORT", "0")):
        ports.append(("udp", int(os.environ["TAK_UDP_IN_PORT"]), "UDP input"))
    for proto, port, what in ports:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM if proto == "tcp" else socket.SOCK_DGRAM)
        try:
            s.bind(("", port))
            report("OK", f"port {port}/{proto}", f"free ({what})")
        except OSError:
            report("FAIL", f"port {port}/{proto}", f"in use ({what})", "stop the other program or change the port")
        finally:
            s.close()


def check_mode():
    """The TAK_MODE and whether its set-up can work. Returns the mode or None."""
    try:
        m = tak_links.mode()
        tak_links.outputs(m)
    except tak_links.ConfigError as exc:
        report("FAIL", "TAK mode", str(exc), "see docs/en/modes.md")
        return None
    report("OK", "TAK mode", m)
    if m == "multicast":
        group, port = tak_links.multicast_group()
        if os.path.exists("/.dockerenv"):
            report("WARN", "multicast", "inside a container",
                   "multicast needs host networking: docker compose -f docker-compose.yml -f docker-compose.multicast.yml up -d (Linux)")
        s = None
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("", port))
            iface = os.environ.get("TAK_MULTICAST_IF", "")
            s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                         socket.inet_aton(group) + socket.inet_aton(iface or "0.0.0.0"))
            report("OK", "multicast group", f"joined {group}:{port}" + (f" on {iface}" if iface else ""))
        except OSError as exc:
            report("FAIL", "multicast group", f"cannot join {group}:{port} ({exc})",
                   "set TAK_MULTICAST_IF=<LAN IPv4 address>; check that the network allows multicast")
        finally:
            if s is not None:
                s.close()
        if os.environ.get("TAK_INGEST", "0") == "1" and not os.environ.get("TAK_INGEST_UIDS"):
            report("WARN", "multicast PLI", "no TAK_INGEST_UIDS: nobody heard on the LAN is published",
                   "set TAK_INGEST_UIDS=<your device uids>")
    return m


def check_tak_side(m) -> None:
    if m is None:  # configuration error, already reported
        return
    in_docker = os.path.exists("/.dockerenv")
    local_out = m == "direct" or (m == "server" and os.environ.get("TAK_LOCAL_OUTPUTS", "0") == "1")
    for t in (tak_links.udp_targets() if local_out else []):
        local = t["host"] in ("127.0.0.1", "localhost")
        if in_docker and local:
            report("WARN", "TAK UDP target", f"{t['host']}:{t['port']} is the container itself",
                   "use host.docker.internal:<port> in TAK_UDP_TARGETS")
        else:
            report("INFO", "TAK UDP target", f"{t['host']}:{t['port']} (set the TAK client's CoT input to this port)")
    server = tak_links.tak_server()
    if server:
        try:
            ctx = tak_links.ssl_context(server["tls"]) if server.get("tls") else None
        except (RuntimeError, OSError, ssl.SSLError) as exc:
            report("FAIL", "TAK Server certificates", str(exc), "check TAK_SERVER_P12 / _PASSWORD / TAK_SERVER_CERT")
            return
        host, port = server["host"], server["port"]
        try:
            with socket.create_connection((host, port), timeout=5) as raw:
                if ctx is not None:
                    with ctx.wrap_socket(raw, server_hostname=host):
                        pass
            report("OK", "TAK Server", f"{host}:{port} {'TLS handshake ok' if ctx else 'TCP ok'}")
        except ssl.SSLCertVerificationError as exc:
            report("FAIL", "TAK Server", f"{host}:{port} certificate not trusted ({exc.verify_message})",
                   "set TAK_SERVER_TRUST_P12 (or TAK_SERVER_CA); for an IP address try TAK_SERVER_VERIFY_HOSTNAME=0")
        except (OSError, ssl.SSLError) as exc:
            report("FAIL", "TAK Server", f"{host}:{port} ({exc})", "check the address, port and the client certificate")
    ingest = os.environ.get("TAK_INGEST", "0") == "1"
    sources = os.environ.get("TAK_INGEST_FROM") or tak_links.default_ingest_from(m or "direct")
    uids = os.environ.get("TAK_INGEST_UIDS", "")
    share = os.environ.get("TAK_SHARE_MARKERS", "0") == "1"
    devices = "any device" if "*" in [u.strip() for u in uids.split(",")] else uids or "on this machine only"
    detail = f"on, from {sources}, devices {devices}" if ingest else "off (nothing is published from TAK)"
    report("WARN" if ingest and "server" in sources else "INFO", "PLI to backbone", detail,
           "TAK_INGEST_FROM=server publishes every TAK Server user's position to the backbone")
    report("INFO", "markers to backbone", f"on: every CoT marker and drawing, devices {devices}"
           if share else "off (TAK_SHARE_MARKERS=1 shares markers and drawings; messages never)")
    if (ingest or share) and not uids and os.path.exists("/.dockerenv"):
        report("WARN", "TAK to backbone", "in Docker nothing arrives from this machine",
               "set TAK_INGEST_UIDS=<device uids> (or *): packets from the host do not come from 127.0.0.1")


def main() -> int:
    print("EFDI TAK relay doctor\n")
    check_python()
    check_zenoh()
    cert = check_identity()
    check_netbird()
    check_router(cert)
    m = check_mode()
    if not check_running_relay():
        check_ports(m)
    check_tak_side(m)
    failed = RESULTS.count("FAIL")
    print(f"\n{failed} failure(s), {RESULTS.count('WARN')} warning(s)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
