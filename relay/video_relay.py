"""Backbone MPEG-TS video -> live RTSP, for TAK's built-in video plugin.

Some vendors on the backbone publish raw MPEG-TS packets (sync byte 0x47) under keys that
match "video" or "keyframe" -- relay/tak_gateway.py's on_any() previously only buffered a
preview snippet of these for the /streams debug page and never forwarded them to TAK.

TAK (ATAK/WinTAK) does not carry video inside CoT; a CoT marker instead references a
stream URL via a <video> element, and TAK's video plugin connects to that URL directly. So
turning backbone video into something TAK can actually play needs two things:
  1. A live RTSP endpoint per camera.
  2. A CoT <video> marker naming that URL, republished periodically like any other track.

ARCHITECTURE, revised after an actual end-to-end test against real ffmpeg found the original
plan didn't work: ffmpeg's RTSP *output* muxer has no server/listen mode at all in current
ffmpeg (confirmed: `ffmpeg -h muxer=rtsp` lists no -rtsp_flags option whatsoever; an earlier
version of this module tried "-rtsp_flags listen" and it silently attempted a client connect
instead, which is why it logged "Connection refused" with nothing ever listening). ffmpeg can
only ever be an RTSP *client* -- pushing to a server, or (from TAK's side) pulling from one.
So one shared RTSP server process is required in the middle: MediaMTX
(github.com/bluenviron/mediamtx, MIT, single static binary, no other deps). One MediaMTX
instance serves every camera on the same host:port, one path per camera
(rtsp://host:port/<cam_id>); each camera's ffmpeg process pushes to it (-c copy remux, no
re-encode), and TAK pulls from the same port. Verified for real: synthetic MPEG-TS -> ffmpeg
push -> MediaMTX -> ffprobe pull reported the correct codec/resolution end to end.

Needs both ffmpeg and mediamtx on PATH; disabled (feed() is a no-op) if either is missing.
Opt-in via GATEWAY_VIDEO=1 (see relay/tak_gateway.py) -- spawning per-camera ffmpeg processes and
a companion server is real overhead, not appropriate for every deployment (e.g. field devices
from tools/make_relay_package.py won't normally want this).

Relay.feed() never writes to its ffmpeg subprocess directly, even though ffmpeg is now the
*pushing* client (which should always be able to write -- MediaMTX, unlike the old listen-mode
plan, does drain input immediately, whether or not any TAK client has pulled that camera yet).
It stays queue + dedicated-writer-thread anyway: feed() runs on the Zenoh subscriber callback
(relay/tak_gateway.py on_any(), the fabric's single dispatch thread), and *any* transient stall
in the ffmpeg or MediaMTX process (a restart, a slow disk, a hung pull client MediaMTX is still
serving) must never be able to block that shared thread. Cheap insurance, kept from the
original design.

CAVEAT: the CoT <video>/<ConnectionEntry> shape below is written from the TAK video-alias
schema as documented by the ATAK plugin ecosystem, not verified against a real TAK client --
same caveat as gateway_core.atak_data_package. The MediaMTX push/pull plumbing IS verified for
real; "does ATAK's video plugin actually offer Play Video and render it" is not. Expect to
adjust attribute names against a real client.
"""
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import time
from xml.sax.saxutils import escape

FFMPEG = shutil.which("ffmpeg")
MEDIAMTX = shutil.which("mediamtx")


def _attr(value) -> str:
    """escape() for a double-quoted XML attribute value: escape() alone only handles &<>, not
    the '"' that would otherwise terminate the attribute early (or break the parse) if it's in
    the value -- e.g. a vendor callsign containing a quote character."""
    return escape(str(value), {'"': "&quot;"})


def safe_cam_id(key: str) -> str:
    """A short, RTSP-path-safe, CoT-UID-safe identifier derived from a backbone key."""
    safe = re.sub(r"[^A-Za-z0-9._-]", "-", key).strip("-")
    return safe[-80:] or "cam"


def _iso(t: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(t))


def video_cot(uid: str, callsign: str, url: str, path: str, port: int, host: str,
              lat: float = 0.0, lon: float = 0.0, hae: float = 9999999.0, ce: float = 9999999.0,
              le: float = 9999999.0, location_known: bool = False, stale_s: float = 120.0,
              now: float = None) -> bytes:
    """CoT event carrying a <video> element, so TAK offers "Play Video" on this marker.

    No independent position source exists for a raw video feed (see module docstring), so
    unless the caller supplies a real lat/lon (location_known=True), this marks the point
    explicitly unknown (ce/le at the CoT "no error estimate" sentinel) rather than implying a
    real location at 0,0.
    """
    now = time.time() if now is None else now
    t = _iso(now)
    stale = _iso(now + stale_s)
    remarks = "backbone video feed" if location_known else "backbone video feed (source position unknown)"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<event version="2.0" uid="{_attr(uid)}" type="b-m-p-s-p-loc" '
        f'time="{t}" start="{t}" stale="{stale}" how="m-g">'
        f'<point lat="{lat:.6f}" lon="{lon:.6f}" hae="{hae}" ce="{ce}" le="{le}"/>'
        '<detail>'
        f'<contact callsign="{_attr(callsign)}"/>'
        f'<remarks>{escape(remarks)}</remarks>'
        f'<video url="{_attr(url)}" uid="{_attr(uid)}">'
        f'<ConnectionEntry networkTimeout="12000" uid="{_attr(uid)}" path="/{_attr(path)}" '
        f'protocol="rtsp" bufferTime="-1" address="{_attr(host)}" port="{port}" '
        f'roverPort="-1" rtspReliable="0" ignoreEmbeddedKLV="false" alias="{_attr(callsign)}"/>'
        '</video>'
        '</detail></event>\n'
    ).encode()


class MediaMTX:
    """The one shared RTSP server every camera's Relay pushes to and every TAK client pulls
    from. Started once by VideoRelayManager, not per camera."""

    def __init__(self, port: int, log=print, binary: str = None):
        self.port = port
        self.log = log
        self.binary = binary or MEDIAMTX
        self.proc = None
        self._cfg_path = None

    def start(self) -> bool:
        if not self.binary:
            return False
        # Minimal config: RTSP only, everything else MediaMTX also serves by default (RTMP,
        # HLS, WebRTC, SRT, MoQ) turned off -- this deployment only ever needs RTSP in and out.
        #
        # `paths: all_others:` is NOT optional -- found by an actual end-to-end test: MediaMTX's
        # own bundled default mediamtx.yml (the one next to the binary in its release tarball)
        # happens to include a permissive catch-all path, which is why an ad-hoc "just run
        # mediamtx from the directory you unpacked it into" test can look like publishing to
        # any path just works. It doesn't: a *truly* config-free run ("using an empty
        # configuration" in its own log) has no paths at all and refuses every publish with
        # "path 'x' is not configured" (400, which ffmpeg's client-side log misreports as a
        # codec problem -- it never got far enough to look at codecs). Without this line every
        # single camera push fails, permanently, the moment this ships with our own minimal
        # config instead of MediaMTX's bundled one.
        config = (
            f"rtsp: yes\nrtspAddress: :{self.port}\n"
            "rtmp: no\nhls: no\nwebrtc: no\nsrt: no\nmoq: no\napi: no\nmetrics: no\n"
            "paths:\n  all_others:\n"
        )
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".yml", prefix="mediamtx-", delete=False)
        f.write(config)
        f.close()
        self._cfg_path = f.name
        self.proc = subprocess.Popen([self.binary, self._cfg_path],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.log(f"[video] mediamtx listening on rtsp://0.0.0.0:{self.port} (pid {self.proc.pid})")
        return True

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def ensure_running(self) -> None:
        """Call periodically; restarts MediaMTX if it died. All active Relay pushers will
        reconnect on their own next restart cycle (see Relay._write_loop)."""
        if self.binary and not self.alive():
            if self.proc is not None:
                self.log("[video] mediamtx exited, restarting")
            self.start()

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.kill()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass


_STOP = object()  # writer-thread sentinel


class Relay:
    """One ffmpeg process per camera, pushing (-c copy remux, no re-encode) MPEG-TS fed on
    stdin to the shared MediaMTX server as an RTSP client.

    feed() never touches the subprocess directly -- see the module docstring for why. It only
    enqueues; a dedicated writer thread owns the actual (normally fast, but never guaranteed)
    write.
    """

    def __init__(self, cam_id: str, mtx_host: str, mtx_port: int, log=print, ffmpeg: str = None,
                 queue_size: int = 64):
        self.cam_id = cam_id
        self.mtx_host = mtx_host
        self.mtx_port = mtx_port
        self.log = log
        self.ffmpeg = ffmpeg or FFMPEG
        self.path = cam_id
        self.push_url = f"rtsp://{mtx_host}:{mtx_port}/{self.path}"
        self.last_feed = time.time()
        self.restarts = 0
        self.dropped = 0
        self.proc = None
        self._stopping = False
        self._q = queue.Queue(maxsize=queue_size)
        self._spawn()
        self._writer = threading.Thread(target=self._write_loop, daemon=True)
        self._writer.start()

    def _spawn(self) -> None:
        cmd = [self.ffmpeg, "-loglevel", "error", "-fflags", "+genpts", "-f", "mpegts", "-i", "pipe:0",
               "-c", "copy", "-rtsp_transport", "tcp", "-f", "rtsp", self.push_url]
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL)
        self.log(f"[video] {self.cam_id}: pushing to {self.push_url} (pid {self.proc.pid})")

    def _write_loop(self) -> None:
        """Runs on its own thread: the only place allowed to block on the ffmpeg process."""
        while True:
            data = self._q.get()
            if data is _STOP:
                return
            if self._stopping:
                continue  # drain to the STOP sentinel without touching a process stop() is killing
            if self.proc.poll() is not None:
                self.log(f"[video] {self.cam_id}: ffmpeg exited (code {self.proc.returncode}), restarting")
                self.restarts += 1
                self._spawn()
            try:
                self.proc.stdin.write(data)
                self.proc.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                if self._stopping:
                    continue
                self.log(f"[video] {self.cam_id}: write failed ({exc}), restarting")
                self.restarts += 1
                self._spawn()

    def feed(self, data: bytes) -> None:
        """Non-blocking: enqueues for the writer thread, dropping the oldest queued chunk (not
        this new one) if the queue is full. Prefers fresh video over a backlog."""
        self.last_feed = time.time()
        try:
            self._q.put_nowait(data)
        except queue.Full:
            self.dropped += 1
            try:
                self._q.get_nowait()
            except queue.Empty:
                pass
            try:
                self._q.put_nowait(data)
            except queue.Full:
                pass

    def status(self) -> dict:
        return {"cam_id": self.cam_id, "push_url": self.push_url,
                "age_s": round(time.time() - self.last_feed, 1), "restarts": self.restarts,
                "dropped": self.dropped, "queued": self._q.qsize(),
                "alive": self.proc is not None and self.proc.poll() is None}

    def stop(self) -> None:
        self._stopping = True  # tells the writer thread not to _spawn() a replacement process
        try:
            self._q.put_nowait(_STOP)
        except queue.Full:
            with self._q.mutex:
                self._q.queue.clear()
            self._q.put_nowait(_STOP)
        if self.proc and self.proc.poll() is None:
            self.proc.kill()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass


class VideoRelayManager:
    """Owns the shared MediaMTX server and one Relay per distinct camera key, and reports which
    cameras are due for their next CoT <video> republish.

    relay_factory/mediamtx_factory are injectable so tests can exercise the camera-tracking /
    idle-release / republish-cadence logic without spawning real ffmpeg or mediamtx processes.
    Pass mediamtx_factory=None to skip starting a server at all (e.g. a fake relay_factory that
    doesn't need one).
    """

    def __init__(self, public_host: str, mtx_port: int, mtx_push_host: str = "127.0.0.1",
                 idle_s: float = 120.0, republish_s: float = 30.0, log=print,
                 relay_factory=Relay, mediamtx_factory=MediaMTX):
        self.public_host = public_host
        self.mtx_port = mtx_port
        self.mtx_push_host = mtx_push_host
        self.idle_s = idle_s
        self.republish_s = republish_s
        self.log = log
        self._relay_factory = relay_factory
        self._lock = threading.Lock()
        self.relays: dict = {}      # cam_id -> Relay
        self._last_cot: dict = {}   # cam_id -> last republish time
        self.mtx = mediamtx_factory(mtx_port, log) if mediamtx_factory else None
        if self.mtx is not None:
            self.mtx.start()

    @property
    def enabled(self) -> bool:
        if self._relay_factory is not Relay:
            return True  # test double: doesn't need real ffmpeg/mediamtx
        return FFMPEG is not None and self.mtx is not None and self.mtx.alive()

    def feed(self, key: str, data: bytes) -> bool:
        """Feed one MPEG-TS chunk for `key`. Returns False if disabled."""
        if not self.enabled:
            return False
        cam_id = safe_cam_id(key)
        with self._lock:
            relay = self.relays.get(cam_id)
            if relay is None:
                relay = self.relays[cam_id] = self._relay_factory(
                    cam_id, self.mtx_push_host, self.mtx_port, self.log)
        relay.feed(data)
        return True

    def due_for_cot(self, now=None) -> dict:
        """{cam_id: Relay} for every active relay whose CoT marker should (re)publish now.
        Also releases (stops) relays idle past idle_s, and restarts mediamtx if it died."""
        now = time.time() if now is None else now
        if self.mtx is not None:
            self.mtx.ensure_running()
        due = {}
        with self._lock:
            for cam_id, relay in list(self.relays.items()):
                if now - relay.last_feed > self.idle_s:
                    self.log(f"[video] {cam_id}: idle {self.idle_s:.0f}s, releasing")
                    relay.stop()
                    del self.relays[cam_id]
                    self._last_cot.pop(cam_id, None)
                    continue
                if now - self._last_cot.get(cam_id, 0) >= self.republish_s:
                    due[cam_id] = relay
                    self._last_cot[cam_id] = now
        return due

    def status(self) -> dict:
        with self._lock:
            relays = {cam_id: relay.status() for cam_id, relay in self.relays.items()}
        return {"mediamtx_alive": self.mtx.alive() if self.mtx is not None else None,
                "public_host": self.public_host, "mtx_port": self.mtx_port, "cameras": relays}

    def stop_all(self) -> None:
        with self._lock:
            for relay in self.relays.values():
                relay.stop()
            self.relays.clear()
            self._last_cot.clear()
        if self.mtx is not None:
            self.mtx.stop()
