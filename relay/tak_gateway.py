#!/usr/bin/env python3
"""TAK gateway: EFDI Zenoh backbone <-> TAK clients / TAK Server.

Backbone -> TAK
  * <org>/sensor/v1/**  (own telemetry JSON)  -> converted to CoT
  * */tak/cot/v1/**     (any vendor's CoT XML) -> validated, rate-limited, forwarded verbatim
  fanned out to every configured output (UDP, TCP server for ATAK/WinTAK, TCP/TLS client
  towards a TAK Server), each with its own reconnect/queue and counters.

TAK -> backbone (optional, TAK_INGEST=1)
  * CoT events that local TAK clients send (UDP input, TCP server) are validated and published
    to <org>/tak/pli/v1/<uid> (friendly PLI by default). Off by default: it writes to the shared
    backbone. Events from a TAK Server link carry other users' positions and are never published
    unless TAK_INGEST_FROM includes "server". TAK_INGEST_UIDS limits publishing to named devices;
    without it only TAK clients on this machine (loopback) may publish.
    Events whose uid the relay itself sent to TAK in the last 60 s are dropped (no echo loops).

Operations
  * GET :8088/healthz  200 when the fabric link is up, else 503
  * GET :8088/metrics  Prometheus text        * GET :8088/status  JSON detail
  * exits (so Docker restarts it) when the fabric link is lost or the feed goes silent.

Config: env for the simple case, or GATEWAY_CONFIG=<json file>:
  {"outputs":[{"type":"udp","host":"host.docker.internal","port":6969},
              {"type":"tcp_server","port":8087},
              {"type":"tcp_client","host":"tak.example","port":8089,
               "tls":{"cert":"c.pem","key":"k.pem","ca":"ca.pem","verify_hostname":false}}],
   "ingest":false}
Simple env: TAK_UDP_TARGETS (host:port[,host:port...]; else TAK_HOST + TAK_UDP_PORT), TAK_PORT, TAK_INGEST,
TAK_INGEST_FROM (local[,server]), TAK_INGEST_UIDS, TAK_SERVER* (see tak_links.py), TAK_MAX_CLIENTS (TCP server, default 64),
GATEWAY_HTTP_PORT, GATEWAY_HTTP_BIND (default 127.0.0.1), XV_MAX_HZ_PER_UID,
GATEWAY_WATCHDOG_S (silence, default 300), GATEWAY_LOST_S (fabric link down, default 300: Zenoh reconnects by itself, a restart costs ~1 min),
GATEWAY_INGEST_ALL=1 (convert every recognisable positional message on the backbone, see backbone_cot.py),
GATEWAY_SOURCES (subset of xml,geotrack,consilium,mavlink,hymots,orion,adsb,alerts,roi,proto), GATEWAY_HYMOTS_INTERVAL_S.

Video (backbone MPEG-TS -> RTSP -> TAK <video> marker; see relay/video_relay.py, opt-in)
GATEWAY_VIDEO=1 (needs GATEWAY_INGEST_ALL=1 too -- video only ever reaches on_any()), needs
both ffmpeg and mediamtx on PATH (mediamtx is the actual RTSP server; ffmpeg's RTSP muxer has
no server mode of its own -- see relay/video_relay.py). GATEWAY_VIDEO_HOST (required: the
address TAK clients reach this gateway at), GATEWAY_VIDEO_PORT (shared RTSP port for every
camera, default 8554), GATEWAY_VIDEO_IDLE_S (stop a camera's relay after this long without
data, default 120), GATEWAY_VIDEO_REPUBLISH_S (CoT <video> marker refresh interval, default 30).
"""
import collections
import ipaddress
import json
import os
import re
import select
import socket
import sys
import threading
import time
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from xml.sax.saxutils import escape, quoteattr

import zenoh

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backbone_cot as bc  # noqa: E402
import cot_guard  # noqa: E402
import gateway_core as core  # noqa: E402
import goat_connect as gc  # noqa: E402
import heartbeat as hb  # noqa: E402
import status_page  # noqa: E402
import stream_view  # noqa: E402
import symbology  # noqa: E402
import tak_links  # noqa: E402
import video_relay  # noqa: E402

__version__ = "1.2.0"
START = time.time()
GATEWAY_SYSTEM = os.environ.get("GATEWAY_SYSTEM", "tak-gateway")
UDP_IN_PORT = int(os.environ.get("TAK_UDP_IN_PORT", "0"))
COUNTERS = collections.Counter()
_clock = threading.Lock()
LAST_SAMPLE = [0.0]
SESSION = [None]
OUTPUTS = []
INGEST = [False]
_limiter = cot_guard.RateLimiter(float(os.environ.get("XV_MAX_HZ_PER_UID", "2")))
_pli_limiter = cot_guard.RateLimiter(1.0)
_INGEST_PREFIXES = tuple(os.environ.get("TAK_INGEST_TYPES", "a-f-").split(","))


def _csv_set(name: str, default: str = "") -> frozenset:
    return frozenset(x.strip() for x in os.environ.get(name, default).split(",") if x.strip())


try:
    MODE, _MODE_ERROR = tak_links.mode(), None
except tak_links.ConfigError as _exc:  # reported by main(); keeps the module importable for tests
    MODE, _MODE_ERROR = "direct", _exc
# Link kinds: "local" (UDP input, TCP server clients), "lan" (multicast group), "server" (TAK Server).
INGEST_FROM = _csv_set("TAK_INGEST_FROM", tak_links.default_ingest_from(MODE))
INGEST_UIDS = _csv_set("TAK_INGEST_UIDS")            # empty = devices on this machine only ("lan" needs the list)
_CONFIG_ERRORS = []  # reported by main(), like _MODE_ERROR, so the module stays importable


def _int_env(name: str, default: int, minimum: int = 1) -> int:
    raw = os.environ.get(name, "").strip() or str(default)
    try:
        value = int(raw)
    except ValueError:
        value = None
    if value is None or value < minimum:
        _CONFIG_ERRORS.append(f"{name}={raw!r} must be a whole number >= {minimum}")
        return default
    return value


MAX_TCP_CLIENTS = _int_env("TAK_MAX_CLIENTS", 64)
MAX_TCP_CLIENTS_PER_IP = _int_env("TAK_MAX_CLIENTS_PER_IP", 8)


_logged_once: set = set()
_logged_once_lock = threading.Lock()


def _log_once(key: str, msg: str) -> None:
    """log(msg) the first time key is seen (bounded, so a flood of addresses cannot grow it)."""
    with _logged_once_lock:
        if key in _logged_once or len(_logged_once) >= 1000:
            return
        _logged_once.add(key)
    log(msg)


def _origin_ip(origin: str) -> str:
    """"1.2.3.4" from "udp_in@1.2.3.4" or "tcp_server:8087@1.2.3.4:5678" ("" if none)."""
    m = re.search(r"@([0-9.]+)", origin)
    return m.group(1) if m else ""


def _from_loopback(origin: str) -> bool:
    """True when origin is this machine."""
    try:
        return ipaddress.ip_address(_origin_ip(origin)).is_loopback
    except ValueError:
        return False


# Added to every CoT the relay sends, so no relay re-publishes what a relay put on TAK.
RELAY_TAG = b"<__efdi_relay/>"
_ECHO_S = 60.0
# (uid, CoT time) -> when the relay sent it to TAK. Keyed on the event time too: a fresh position
# from your own device must still be published even if someone mirrored an older one back to us.
_forwarded: dict = {}
_forwarded_lock = threading.Lock()
_COT_TYPE = os.environ.get("COT_TYPE", "a-h-A-M-F-Q")
INGEST_ALL = os.environ.get("GATEWAY_INGEST_ALL", "0") == "1"
SOURCES = tuple(x for x in os.environ.get("GATEWAY_SOURCES", ",".join(bc.ALL_SOURCES)).split(",") if x)
_SKIP_KEY_PARTS = ("video", "asterix-raw", "keyframe")
# "imagery" used to be in here too, to avoid running the converter over vendors' actual image bytes. Dropped: at
# least one vendor (mantis/alpha-fob) publishes the same position-track protobuf as everyone else under a path
# that happens to contain "imagery" (.../imagery/v1) but carries no image at all; bc.convert() already returns []
# for genuine image bytes (their first byte matches none of xml/json/protobuf), so the keyword added no safety.
_MIN_INTERVAL_S = {"xml": 0.5, "geotrack": 1.0, "consilium": 1.0, "mavlink": 1.0,
                   "hymots": float(os.environ.get("GATEWAY_HYMOTS_INTERVAL_S", "10")),
                   "orion": 2.0, "adsb": 1.0, "alerts": 5.0, "roi": 1.0, "proto": 1.0}
# One limiter per recognised source; a source without its own interval gets 1 s.
_src_limiters = {k: cot_guard.RateLimiter(1.0 / _MIN_INTERVAL_S.get(k, 1.0)) for k in bc.ALL_SOURCES}
_seen: dict = {}
_seen_lock = threading.Lock()
STREAMS = stream_view.StreamStats(gc.ORG)

# Video restream (backbone MPEG-TS -> RTSP -> TAK <video> marker). Opt-in: needs ffmpeg AND
# mediamtx on PATH, opens one shared RTSP port, and only makes sense with GATEWAY_INGEST_ALL=1
# (video only ever reaches on_any()). See relay/video_relay.py for the architecture and the
# caveats on the CoT <video> element shape.
VIDEO_ENABLED = os.environ.get("GATEWAY_VIDEO", "0") == "1"
VIDEO = None
if VIDEO_ENABLED:
    _vhost = os.environ.get("GATEWAY_VIDEO_HOST")
    if not _vhost:
        print("[tak-gateway] GATEWAY_VIDEO=1 but GATEWAY_VIDEO_HOST is not set (the address TAK "
              "clients will connect to for RTSP) -- video restream disabled", flush=True)
    else:
        VIDEO = video_relay.VideoRelayManager(
            public_host=_vhost, mtx_port=int(os.environ.get("GATEWAY_VIDEO_PORT", "8554")),
            idle_s=float(os.environ.get("GATEWAY_VIDEO_IDLE_S", "120")),
            republish_s=float(os.environ.get("GATEWAY_VIDEO_REPUBLISH_S", "30")))
        if not video_relay.FFMPEG:
            print("[tak-gateway] GATEWAY_VIDEO=1 but ffmpeg is not on PATH -- video restream disabled",
                  flush=True)
        elif not video_relay.MEDIAMTX:
            print("[tak-gateway] GATEWAY_VIDEO=1 but mediamtx is not on PATH -- video restream disabled",
                  flush=True)


def inc(name: str, n: int = 1) -> None:
    with _clock:
        COUNTERS[name] += n


def log(msg: str) -> None:
    print(f"[tak-gateway] {msg}", flush=True)


# ---------------------------------------------------------------- telemetry -> CoT
def _iso(t: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(t))


def telemetry_to_cot(d: dict) -> bytes:
    uid = str(d.get("source", "uav-00")).replace("/", "-")
    lost = bool(d.get("lost", False))
    speed_ms = d.get("speed_kmh", 0.0) / 3.6
    cot_type, basis = symbology.cot_type(text=f"{d.get('type', '')} {uid}", hae=d.get("alt"), speed_mps=speed_ms,
                                         default_affiliation="u", default_dim="A" if "uav" in uid.lower() else "G")
    now = time.time()
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<event version="2.0" uid={quoteattr(uid)} type={quoteattr(cot_type)} time="{_iso(now)}" start="{_iso(now)}" '
        f'stale="{_iso(now - 1 if lost else now + 60)}" how="m-g">'
        f'<point lat="{d.get("lat", 0.0):.6f}" lon="{d.get("lon", 0.0):.6f}" hae="{float(d.get("alt", 50)):.1f}" ce="10" le="10"/>'
        '<detail>'
        f'<track speed="{d.get("speed_kmh", 0.0) / 3.6:.1f}" course="{d.get("heading", 0.0):.1f}"/>'
        f'<uid Droid={quoteattr(uid)}/><contact callsign={quoteattr(uid)} endpoint="*:-1:stcp"/>'
        f'<remarks>{"CONTACT LOST" if lost else escape(str(d.get("phase", "?")).upper())}'
        f'  spd={d.get("speed_kmh", 0):.0f}km/h [type:{escape(str(basis))}]</remarks>'
        '</detail></event>\n'
    )
    return xml.encode()


# ---------------------------------------------------------------- ingest (TAK -> backbone)
def _safe_key(uid: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", uid)[:96] or "unknown"


def _recently_forwarded(uid: str, when: str) -> bool:
    with _forwarded_lock:
        t = _forwarded.get((uid, when))
    return t is not None and time.time() - t < _ECHO_S


def _remember_forwarded(data: bytes) -> None:
    try:
        root = ET.fromstring(data.strip().split(b"?>", 1)[-1] if data.lstrip().startswith(b"<?") else data.strip())
    except ET.ParseError:
        return
    uid = root.get("uid", "")
    if not uid:
        return
    now = time.time()
    with _forwarded_lock:
        _forwarded[(uid, root.get("time", ""))] = now
        if len(_forwarded) > 20000:
            for k in [k for k, t in _forwarded.items() if now - t > _ECHO_S]:
                _forwarded.pop(k, None)


def tag(data: bytes) -> bytes:
    """data with RELAY_TAG inside <detail> (TAK clients keep unknown detail elements)."""
    if RELAY_TAG in data:
        return data
    i = data.rfind(b"</detail>")
    if i >= 0:
        return data[:i] + RELAY_TAG + data[i:]
    m = re.search(rb"<detail\s*/>", data)
    if m:
        return data[:m.start()] + b"<detail>" + RELAY_TAG + b"</detail>" + data[m.end():]
    j = data.rfind(b"</event>")
    return data[:j] + b"<detail>" + RELAY_TAG + b"</detail>" + data[j:] if j >= 0 else data


def ingest_event(ev: bytes, origin: str, kind: str = "local") -> None:
    """Publish one CoT event from a TAK link as PLI. kind: "local", "lan" or "server"."""
    if not INGEST[0] or SESSION[0] is None:
        return
    if kind not in INGEST_FROM:
        inc('gateway_ingest_dropped_total{reason="not-local"}')
        return
    if RELAY_TAG in ev:
        inc('gateway_ingest_dropped_total{reason="relayed"}')
        return
    # Without an allowlist only this machine's TAK app may publish: anyone else on the network
    # could otherwise put positions on the fabric under the org's identity.
    if kind == "local" and not INGEST_UIDS and not _from_loopback(origin):
        inc('gateway_ingest_dropped_total{reason="not-loopback"}')
        _log_once(_origin_ip(origin), f"PLI from {origin} not published: not this machine and "
                  "TAK_INGEST_UIDS is empty (list the device uid to publish it)")
        return
    ok, reason = cot_guard.validate_cot(ev)
    if not ok:
        inc(f'gateway_ingest_dropped_total{{reason="{reason}"}}')
        return
    try:
        root = ET.fromstring(ev)
    except ET.ParseError:
        return
    typ = root.get("type", "")
    if typ.startswith("t-") or not typ.startswith(_INGEST_PREFIXES):
        inc('gateway_ingest_dropped_total{reason="type"}')
        return
    uid = root.get("uid", "")
    if (INGEST_UIDS or kind == "lan") and uid not in INGEST_UIDS:
        inc('gateway_ingest_dropped_total{reason="not-allowed"}')
        return
    if _recently_forwarded(uid, root.get("time", "")):
        inc('gateway_ingest_dropped_total{reason="echo"}')
        return
    if not _pli_limiter.allow(uid):
        inc('gateway_ingest_dropped_total{reason="rate-limited"}')
        return
    try:
        SESSION[0].put(f"{gc.ORG}/tak/pli/v1/{_safe_key(uid)}", ev)
        inc("gateway_ingest_published_total")
    except Exception as exc:  # noqa: BLE001
        inc("gateway_ingest_errors_total")
        log(f"ingest publish failed: {exc}")


def _reader(sock: socket.socket, origin: str, kind: str = "local") -> None:
    buf = bytearray()
    try:
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                return
            buf.extend(chunk)
            for ev in core.split_cot_stream(buf):
                ingest_event(ev, origin, kind)
    except OSError:
        return


# ---------------------------------------------------------------- outputs
class UdpOutput:
    def __init__(self, cfg):
        self.name = f"{'multicast' if cfg.get('multicast') else 'udp'}:{cfg['host']}:{cfg['port']}"
        self.addr = (cfg["host"], int(cfg["port"]))
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        if cfg.get("multicast"):
            self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, int(cfg.get("ttl", 1)))
            # Loop back, so TAK on this same machine gets the markers too.
            self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
            if cfg.get("iface"):
                self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(cfg["iface"]))

    def send(self, data: bytes) -> None:
        try:
            self.sock.sendto(data, self.addr)
            inc(f'gateway_output_sent_total{{output="{self.name}"}}')
        except OSError:
            inc(f'gateway_output_errors_total{{output="{self.name}"}}')

    def status(self) -> dict:
        return {"name": self.name, "connected": True}


class _TcpClient:
    """One connected TAK client: its own bounded queue and writer thread.

    send() never blocks the caller (the Zenoh callback thread). A client that stops
    reading only overflows its own queue; after `stall_s` without progress it is dropped.
    """

    def __init__(self, conn, name, on_close, queue_len=1000, stall_s=10.0):
        self.conn, self.name, self.on_close, self.stall_s = conn, name, on_close, stall_s
        self.q = collections.deque(maxlen=queue_len)
        self.cv = threading.Condition()
        self.closed = False
        self.ip = ""
        threading.Thread(target=self._write, daemon=True).start()

    def send(self, data: bytes) -> bool:
        with self.cv:
            if self.closed:
                return False
            overflow = len(self.q) == self.q.maxlen
            self.q.append(data)
            self.cv.notify()
        return not overflow

    def _write(self):
        # A blocking sendall on a non-reading peer would hang forever; poll writability instead.
        import select
        try:
            while True:
                with self.cv:
                    while not self.q and not self.closed:
                        self.cv.wait(1.0)
                    if self.closed:
                        return
                    data = self.q.popleft()
                view = memoryview(data)
                deadline = time.monotonic() + self.stall_s
                while view:
                    _, w, _ = select.select([], [self.conn], [], 1.0)
                    if w:
                        # small slices: a "writable" socket always has room for 4 KiB, so this
                        # send cannot block (the socket stays blocking for the reader thread)
                        n = self.conn.send(view[:4096])
                        view = view[n:]
                        deadline = time.monotonic() + self.stall_s
                    elif time.monotonic() > deadline:
                        raise OSError("client stalled")
        except (OSError, ValueError) as exc:
            log(f"{self.name}: dropped ({exc})")
        finally:
            self.close()

    def close(self):
        with self.cv:
            if self.closed:
                return
            self.closed = True
            self.cv.notify()
        try:
            self.conn.close()
        except OSError:
            pass
        self.on_close(self)


class TcpServerOutput:
    def __init__(self, cfg):
        self.name = f"tcp_server:{cfg['port']}"
        self.clients = []
        self.lock = threading.Lock()
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("", int(cfg["port"])))
        srv.listen(20)
        threading.Thread(target=self._accept, args=(srv,), daemon=True).start()

    def _accept(self, srv):
        while True:
            try:
                conn, addr = srv.accept()
            except OSError:
                return
            with self.lock:
                same_ip = sum(1 for c in self.clients if c.ip == addr[0])
                why = (f"{MAX_TCP_CLIENTS} clients already (TAK_MAX_CLIENTS)"
                       if len(self.clients) >= MAX_TCP_CLIENTS else
                       f"{MAX_TCP_CLIENTS_PER_IP} clients from this address (TAK_MAX_CLIENTS_PER_IP)"
                       if same_ip >= MAX_TCP_CLIENTS_PER_IP else "")
            if why:
                # Per address too, so one host holding idle connections cannot lock out the others.
                conn.close()
                inc(f'gateway_output_rejected_total{{output="{self.name}"}}')
                log(f"{self.name}: refused {addr[0]}:{addr[1]}, {why}")
                continue
            client = _TcpClient(conn, f"{self.name}@{addr[0]}:{addr[1]}", self._forget)
            client.ip = addr[0]
            with self.lock:
                self.clients.append(client)
                total = len(self.clients)
            log(f"{self.name}: client {addr[0]}:{addr[1]} connected (total {total})")
            inc(f'gateway_output_connects_total{{output="{self.name}"}}')
            threading.Thread(target=self._read_then_drop, args=(client,), daemon=True).start()

    def _read_then_drop(self, client):
        _reader(client.conn, client.name)
        client.close()

    def _forget(self, client):
        with self.lock:
            if client in self.clients:
                self.clients.remove(client)

    def send(self, data: bytes) -> None:
        with self.lock:
            clients = list(self.clients)
        for c in clients:
            if c.send(data):
                inc(f'gateway_output_sent_total{{output="{self.name}"}}')
            else:
                inc(f'gateway_output_dropped_total{{output="{self.name}"}}')

    def status(self) -> dict:
        with self.lock:
            n = len(self.clients)
        return {"name": self.name, "connected": True, "clients": n}


class TcpClientOutput:
    """Streams CoT to a TAK Server (plain TCP or TLS) with reconnect and a bounded queue."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.name = f"tcp_client:{cfg['host']}:{cfg['port']}"
        # Built once: a wrong .p12 password or a missing file stops the relay at start, loudly.
        self.ctx = tak_links.ssl_context(cfg["tls"]) if cfg.get("tls") else None
        self.q = collections.deque(maxlen=int(cfg.get("queue", 1000)))
        self.cv = threading.Condition()
        self.connected = False
        self.stall_s = float(cfg.get("stall_s", 10.0))
        threading.Thread(target=self._run, daemon=True).start()

    def _connect(self):
        s = socket.create_connection((self.cfg["host"], int(self.cfg["port"])), timeout=10)
        if self.ctx is not None:
            s = self.ctx.wrap_socket(s, server_hostname=self.cfg["host"])
        s.settimeout(self.stall_s)  # a send or receive that makes no progress drops the link
        return s

    def _serve(self, sock) -> None:
        """Send queued CoT and read what the server sends, both from this one thread: an SSL socket
        must not be read and written from two threads at once."""
        buf = bytearray()
        while True:
            with self.cv:
                if not self.q:
                    self.cv.wait(0.2)
                data = self.q.popleft() if self.q else None
            if data is not None:
                sock.sendall(data)
                inc(f'gateway_output_sent_total{{output="{self.name}"}}')
            # pending(): bytes the SSL layer has already decrypted, invisible to select().
            pending = sock.pending() if hasattr(sock, "pending") else 0
            if pending or select.select([sock], [], [], 0)[0]:
                chunk = sock.recv(65536)
                if not chunk:
                    raise OSError("closed by the server")
                buf.extend(chunk)
                for ev in core.split_cot_stream(buf):
                    ingest_event(ev, self.name, "server")

    def _run(self):
        delay = 2.0
        while True:
            try:
                sock = self._connect()
            except Exception as exc:  # noqa: BLE001
                inc(f'gateway_output_errors_total{{output="{self.name}"}}')
                log(f"{self.name}: connect failed ({exc}); retry in {delay:.0f}s")
                time.sleep(delay)
                delay = min(delay * 2, 60.0)
                continue
            delay = 2.0
            self.connected = True
            log(f"{self.name}: connected")
            try:
                self._serve(sock)
            except OSError as exc:  # includes send/receive timeouts
                log(f"{self.name}: link lost ({exc})")
            finally:
                self.connected = False
                try:
                    sock.close()
                except OSError:
                    pass

    def send(self, data: bytes) -> None:
        with self.cv:
            if len(self.q) == self.q.maxlen:
                inc(f'gateway_output_dropped_total{{output="{self.name}"}}')
            self.q.append(data)
            self.cv.notify()

    def status(self) -> dict:
        return {"name": self.name, "connected": self.connected, "queued": len(self.q)}


def _datagram_event(data: bytes) -> list:
    """The one CoT event of a UDP datagram, or [] (TAK sends one event per datagram; more means
    something was hidden, e.g. an event inside a comment)."""
    events = core.split_cot_stream(bytearray(data))
    if len(events) > 1:
        inc('gateway_ingest_dropped_total{reason="multi-event-datagram"}')
        return []
    return events


def start_udp_input(port: int) -> None:
    """Receive CoT that a TAK client sends by UDP (its UDP output) and feed the PLI ingest."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("", port))

    def loop():
        while True:
            try:
                data, addr = sock.recvfrom(65535)
            except OSError:
                return
            inc("gateway_udp_in_datagrams_total")
            for ev in _datagram_event(data):
                ingest_event(ev, f"udp_in@{addr[0]}")

    threading.Thread(target=loop, daemon=True).start()
    log(f"udp input listening on :{port} (TAK -> backbone ingest={'on' if INGEST[0] else 'off'})")


def open_multicast_listener(group: str, port: int, iface: str = "") -> socket.socket:
    """UDP socket joined to the multicast group; shares the port with TAK clients on this machine."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if hasattr(socket, "SO_REUSEPORT"):
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    sock.bind(("", port))
    mreq = socket.inet_aton(group) + socket.inet_aton(iface or "0.0.0.0")
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    return sock


def start_multicast_input() -> None:
    """PLI from TAK clients on the LAN (they send their SA to the group). Kind "lan"."""
    group, port = tak_links.multicast_group()
    try:
        sock = open_multicast_listener(group, port, os.environ.get("TAK_MULTICAST_IF", ""))
    except OSError as exc:
        # e.g. a TAK app on this machine holds the port exclusively. Sending still works.
        inc("gateway_multicast_listen_errors_total")
        log(f"multicast input on {group}:{port} unavailable ({exc}); sending only, no PLI from the LAN")
        return

    def loop():
        while True:
            try:
                data, addr = sock.recvfrom(65535)
            except OSError:
                return
            inc("gateway_multicast_in_datagrams_total")
            for ev in _datagram_event(data):
                ingest_event(ev, f"multicast@{addr[0]}", "lan")

    threading.Thread(target=loop, daemon=True).start()
    log(f"multicast input on {group}:{port} (published only for TAK_INGEST_UIDS: "
        f"{', '.join(sorted(INGEST_UIDS)) or 'none'})")


def health() -> tuple:
    """(ok, reasons) for /status and the heartbeat."""
    reasons = []
    if not fabric_up():
        reasons.append("fabric link down")
    age = time.time() - LAST_SAMPLE[0] if LAST_SAMPLE[0] else None
    if age is not None and age > 120:
        reasons.append(f"no backbone samples for {age:.0f}s")
    for o in OUTPUTS:
        st = o.status()
        if not st.get("connected"):
            reasons.append(f"output {st.get('name')} not connected")
    return (not reasons), reasons


def build_outputs(cfg: dict) -> list:
    made = []
    for o in cfg.get("outputs", []):
        kind = o.get("type")
        if kind == "udp":
            made.append(UdpOutput(o))
        elif kind == "tcp_server":
            made.append(TcpServerOutput(o))
        elif kind == "tcp_client":
            made.append(TcpClientOutput(o))
        else:
            log(f"unknown output type {kind!r} ignored")
    return made


def load_config() -> dict:
    path = os.environ.get("GATEWAY_CONFIG")
    if path:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {
        "outputs": tak_links.outputs(MODE),
        "ingest": os.environ.get("TAK_INGEST", "0") == "1",
    }


# ---------------------------------------------------------------- dispatch + subscriptions
def dispatch(data: bytes) -> None:
    if INGEST[0]:
        _remember_forwarded(data)
    data = tag(data)
    for o in OUTPUTS:
        try:
            o.send(data)
        except Exception:  # noqa: BLE001
            inc(f'gateway_output_errors_total{{output="{o.name}"}}')


def on_telemetry(sample) -> None:
    LAST_SAMPLE[0] = time.time()
    inc('gateway_cot_in_total{source="telemetry"}')
    try:
        d = json.loads(sample.payload.to_bytes())
        data = telemetry_to_cot(d)
    except (ValueError, KeyError, TypeError, AttributeError):
        inc('gateway_cot_dropped_total{reason="bad-telemetry"}')
        return
    # A "lost" event is stale on purpose (it removes the track), so check it as of a moment ago.
    ok, reason = cot_guard.validate_cot(data, now=time.time() - 5 if d.get("lost") else None)
    if not ok:
        inc(f'gateway_cot_dropped_total{{reason="{reason}"}}')
        return
    dispatch(data)


def on_cot(sample) -> None:
    LAST_SAMPLE[0] = time.time()
    data = sample.payload.to_bytes()
    if not data.lstrip().startswith(b"<"):
        return
    inc('gateway_cot_in_total{source="backbone-cot"}')
    ok, reason = cot_guard.validate_cot(data)
    if not ok:
        inc(f'gateway_cot_dropped_total{{reason="{reason}"}}')
        return
    if not _limiter.allow(cot_guard.uid_of(data)):
        inc('gateway_cot_dropped_total{reason="rate-limited"}')
        return
    dispatch(data)


def _dup(uid: str, data: bytes) -> bool:
    """True if this exact event (uid + time attribute) was forwarded in the last 10 s (same event via several keys)."""
    m = re.search(rb'time="([^"]+)"', data[:600])
    key = (uid, m.group(1) if m else b"")
    now = time.time()
    with _seen_lock:
        if key in _seen and now - _seen[key] < 10:
            return True
        _seen[key] = now
        if len(_seen) > 20000:
            for k in [k for k, t in _seen.items() if now - t > 10]:
                _seen.pop(k, None)
    return False


def on_any(sample) -> None:
    """Universal intake: every recognisable positional message on the backbone becomes CoT."""
    key = str(sample.key_expr)
    try:
        size = len(sample.payload)
    except TypeError:
        size = 0
    own_internal = (key.startswith(f"{gc.ORG}/sensor/v1/") or key.startswith(f"{gc.ORG}/tak/pli/v1/")
                    or "/heartbeat/" in key)
    if own_internal or any(p in key for p in _SKIP_KEY_PARTS):
        # own telemetry (handled separately), our own PLI (would echo back to TAK), heartbeats, media:
        # counted for the /streams view, and (video only, if GATEWAY_VIDEO=1) restreamed to TAK -- never
        # run through bc.convert(), which only understands positional formats, not video bytes.
        hint = "video/binary" if any(p in key for p in ("video", "keyframe")) else ("json" if own_internal else "")
        full = None
        if hint == "video/binary":
            try:
                full = sample.payload.to_bytes()
            except Exception:  # noqa: BLE001
                full = None
        small = full if (full is not None and size <= 20000) else None
        STREAMS.record(key, size, b"", (), hint, payload=small)
        if VIDEO is not None and full is not None and full[:1] == b"\x47":
            if VIDEO.feed(key, full):
                inc('gateway_video_bytes_total', size)
        return
    if size > 2_000_000:
        STREAMS.record(key, size, b"", (), "large")
        return
    LAST_SAMPLE[0] = time.time()
    try:
        payload = sample.payload.to_bytes()
        results = bc.convert(key, payload, SOURCES)
    except Exception:  # noqa: BLE001
        inc('gateway_cot_dropped_total{reason="convert-error"}')
        return
    STREAMS.record(key, size, payload[:240], tuple(r[0] for r in results[:1]), payload=payload)
    for source, uid, data in results:
        inc(f'gateway_cot_in_total{{source="{source}"}}')
        ok, reason = cot_guard.validate_cot(data)
        if not ok:
            inc(f'gateway_cot_dropped_total{{reason="{reason}"}}')
            continue
        uid = uid or cot_guard.uid_of(data)
        if not _src_limiters[source].allow(uid):
            inc('gateway_cot_dropped_total{reason="rate-limited"}')
            continue
        if source == "xml" and _dup(uid, data):
            inc('gateway_cot_dropped_total{reason="duplicate"}')
            continue
        m = re.search(rb'type="([A-Za-z0-9_.-]{1,40})"', data[:400])
        if m:
            inc(f'gateway_cot_type_total{{source="{source}",type="{m.group(1).decode("ascii", "replace")}"}}')
        dispatch(data)


# ---------------------------------------------------------------- HTTP ops endpoints
def fabric_up() -> bool:
    s = SESSION[0]
    if s is None:
        return False
    try:
        return bool(list(s.info.routers_zid()))
    except Exception:  # noqa: BLE001
        return False


def snapshot():
    with _clock:
        counters = dict(COUNTERS)
    age = time.time() - LAST_SAMPLE[0] if LAST_SAMPLE[0] else -1
    gauges = {
        "gateway_fabric_up": int(fabric_up()),
        "gateway_uptime_seconds": int(time.time() - START),
        "gateway_last_sample_age_seconds": round(age, 1),
    }
    for o in OUTPUTS:
        gauges[f'gateway_output_connected{{output="{o.name}"}}'] = int(bool(o.status().get("connected")))
    return counters, gauges


class Ops(BaseHTTPRequestHandler):
    def log_message(self, *a):  # silence
        pass

    def _send(self, code, body, ctype="application/json"):
        b = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        counters, gauges = snapshot()
        if self.path in ("/", "/index.html"):
            self._send(200, status_page.PAGE, "text/html; charset=utf-8")
        elif self.path == "/healthz":
            ok = fabric_up()
            self._send(200 if ok else 503, json.dumps({"fabric_up": ok}))
        elif self.path == "/metrics":
            self._send(200, core.prometheus_text(counters, gauges), "text/plain; version=0.0.4")
        elif self.path in ("/streams", "/streams/"):
            self._send(200, stream_view.PAGE, "text/html; charset=utf-8")
        elif self.path.startswith("/api/preview"):
            from urllib.parse import parse_qs, urlparse
            group = (parse_qs(urlparse(self.path).query).get("g") or [""])[0]
            data, kind = STREAMS.sample(group)
            img = stream_view.extract_image(data) if data else None
            if img is None:
                ts = STREAMS.video(group)
                img = stream_view.video_frame_jpeg(ts) if ts else None
            if img is None:
                return self._send(404, json.dumps({"error": "no image available in this stream"}))
            self.send_response(200)
            self.send_header("Content-Type", "image/png" if img[:4] == bytes([0x89, 0x50, 0x4E, 0x47]) else "image/jpeg")
            self.send_header("Content-Length", str(len(img)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(img)
        elif self.path.startswith("/api/sample") or self.path.startswith("/api/video"):
            from urllib.parse import parse_qs, urlparse
            u = urlparse(self.path)
            group = (parse_qs(u.query).get("g") or [""])[0]
            if u.path == "/api/video":
                data = STREAMS.video(group)
                kind = "video-ts"
            else:
                data, kind = STREAMS.sample(group)
            if data is None:
                return self._send(404, json.dumps({"error": "no such stream or nothing buffered"}))
            b = data
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("X-Stream-Kind", str(kind))
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)
        elif self.path == "/api/streams":
            self._send(200, json.dumps(STREAMS.snapshot()))
        elif self.path == "/status":
            ok, reasons = health()
            self._send(200, json.dumps({"healthy": ok, "reasons": reasons, "version": __version__, "mode": MODE, "org": gc.ORG,
                                        "system": GATEWAY_SYSTEM, "counters": counters, "gauges": gauges,
                                        "outputs": [o.status() for o in OUTPUTS], "ingest": INGEST[0],
                                        "ingest_from": sorted(INGEST_FROM), "ingest_uids": sorted(INGEST_UIDS),
                                        "video": VIDEO.status() if VIDEO is not None else None}, indent=1))
        else:
            self._send(404, '{"error":"not found"}')


# ---------------------------------------------------------------- main
def open_session_retry():
    delay = 5.0
    while True:
        try:
            conf, is_real = gc.make_config()
            return zenoh.open(conf), is_real
        except Exception as exc:  # noqa: BLE001
            log(f"fabric unavailable ({exc}); retry in {delay:.0f}s")
            time.sleep(delay)
            delay = min(delay * 2, 60.0)


def main() -> None:
    if _MODE_ERROR is not None:
        raise SystemExit(f"configuration error: {_MODE_ERROR}")
    if _CONFIG_ERRORS:
        raise SystemExit("configuration error: " + "; ".join(_CONFIG_ERRORS))
    try:
        cfg = load_config()
        INGEST[0] = bool(cfg.get("ingest"))
        OUTPUTS.extend(build_outputs(cfg))
    except (ValueError, RuntimeError, OSError) as exc:  # ConfigError, bad .p12 / PEM, ssl.SSLError
        raise SystemExit(f"configuration error: {exc}  (check with: python relay/doctor.py)") from None
    port = int(os.environ.get("GATEWAY_HTTP_PORT", "8088"))
    # /api/sample serves backbone payloads without auth: this machine only, unless set otherwise.
    http_bind = os.environ.get("GATEWAY_HTTP_BIND", "127.0.0.1")
    threading.Thread(target=ThreadingHTTPServer((http_bind, port), Ops).serve_forever, daemon=True).start()
    log(f"v{__version__} mode={MODE} org={gc.ORG} outputs={[o.name for o in OUTPUTS]} ingest={INGEST[0]} "
        f"ingest_from={','.join(sorted(INGEST_FROM))} ingest_uids={len(INGEST_UIDS) or 'this machine'} http={http_bind}:{port}")
    if INGEST[0] and not INGEST_UIDS and os.path.exists("/.dockerenv"):
        log("WARNING: TAK_INGEST=1 without TAK_INGEST_UIDS in Docker publishes nothing: packets from the "
            "host do not come from 127.0.0.1. Set TAK_INGEST_UIDS to the device uids.")

    if UDP_IN_PORT:
        start_udp_input(UDP_IN_PORT)
    if MODE == "multicast" and INGEST[0]:
        if not INGEST_UIDS:
            log("WARNING: TAK_MODE=multicast hears every TAK user on the LAN; nobody is published "
                "until TAK_INGEST_UIDS names your devices")
        start_multicast_input()
    session, is_real = open_session_retry()
    SESSION[0] = session
    if is_real and os.environ.get("GATEWAY_HEARTBEAT", "1") == "1":
        hb.Heartbeat(session, gc.ORG, GATEWAY_SYSTEM, version=os.environ.get("GATEWAY_VERSION", __version__),
                     interval=float(os.environ.get("GOAT_HEARTBEAT_INTERVAL_S", "60")),
                     health_fn=lambda: health()[0], display_name=GATEWAY_SYSTEM, log=log).start()
    tele_key = f"{gc.KEY_PREFIX}/**"
    cot_key = os.environ.get("GATEWAY_COT_KE", "*/tak/cot/v1/**")
    session.declare_subscriber(tele_key, on_telemetry)
    if INGEST_ALL:
        session.declare_subscriber("**", on_any)
        cot_key = f"** (all vendors; sources={','.join(SOURCES)})"
    else:
        session.declare_subscriber(cot_key, on_cot)
    log(f"{'REAL FABRIC' if is_real else 'local router'}  telemetry={tele_key}  cot={cot_key}")
    if VIDEO is not None:
        log(f"video restream {'enabled' if VIDEO.enabled else 'disabled (missing ffmpeg/mediamtx)'}: "
            f"public_host={VIDEO.public_host} port={VIDEO.mtx_port}")

    silence_s = float(os.environ.get("GATEWAY_WATCHDOG_S", "300"))
    lost_s = float(os.environ.get("GATEWAY_LOST_S", "300"))
    lost_since = None
    last_stats = time.time()
    while True:
        time.sleep(1)
        now = time.time()
        if VIDEO is not None:
            for cam_id, relay in VIDEO.due_for_cot(now).items():
                public_url = f"rtsp://{VIDEO.public_host}:{VIDEO.mtx_port}/{relay.path}"
                data = video_relay.video_cot(uid=f"video-{cam_id}", callsign=cam_id, url=public_url,
                                              path=relay.path, port=VIDEO.mtx_port, host=VIDEO.public_host, now=now)
                inc('gateway_video_cot_total')
                dispatch(data)
        if fabric_up():
            lost_since = None
        else:
            lost_since = lost_since or now
            if lost_s > 0 and now - lost_since > lost_s:
                log(f"WATCHDOG: fabric link down {lost_s:.0f}s, exiting for restart")
                os._exit(1)
        if silence_s > 0 and LAST_SAMPLE[0] and now - LAST_SAMPLE[0] > silence_s:
            log(f"WATCHDOG: no samples for {silence_s:.0f}s, exiting for restart")
            os._exit(1)
        if now - last_stats >= 30:
            last_stats = now
            counters, gauges = snapshot()
            log(f"stats up={gauges['gateway_fabric_up']} last_sample_age={gauges['gateway_last_sample_age_seconds']}s "
                f"{ {k: v for k, v in counters.items() if 'sent_total' in k or 'in_total' in k or 'dropped' in k} }")


if __name__ == "__main__":
    main()
