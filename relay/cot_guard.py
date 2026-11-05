"""Sanity checks for CoT XML before it is forwarded to a TAK client.

Other vendors' CoT is forwarded verbatim, so a malformed event must not reach
a TAK client (some have crashed on odd input). Pure functions, no I/O.
"""
import re
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

MAX_BYTES = 64 * 1024
_EVENT_OPEN = re.compile(rb"<event[\s/>]")
_EVENT_CLOSE = re.compile(rb"</event\s*>")
_DECLARED_ENCODING = re.compile(rb"""\s*<\?xml[^>]*\bencoding\s*=\s*["']([^"']+)["']""", re.I)
_ASCII_COMPATIBLE = {b"utf-8", b"utf8", b"us-ascii", b"ascii", b"iso-8859-1", b"latin-1", b"latin1"}


def _parse_time(s: str) -> float:
    s = s.strip()
    fmt = "%Y-%m-%dT%H:%M:%S.%fZ" if "." in s else "%Y-%m-%dT%H:%M:%SZ"
    return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc).timestamp()


def validate_cot(data: bytes, now: float = None):
    """Return (True, "") or (False, reason)."""
    if len(data) > MAX_BYTES:
        return False, "too-large"
    # UTF-8 (or another ASCII-compatible encoding) only. In UTF-16/32 the byte checks below would
    # see nothing while the parser still decodes the text, DTD included.
    if b"\x00" in data:
        return False, "not-utf8"
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False, "not-utf8"
    m = _DECLARED_ENCODING.match(data)
    if m and m.group(1).lower() not in _ASCII_COMPATIBLE:
        return False, "not-utf8"
    # Anywhere, not just at the start: a comment can push a DTD past any prefix check.
    lower = data.lower()
    if b"<!doctype" in lower or b"<!entity" in lower:
        return False, "dtd-not-allowed"
    try:
        ev = ET.fromstring(data.strip())
    except ET.ParseError:
        return False, "not-xml"
    if ev.tag != "event":
        return False, "not-event"
    # Exactly one event. A second one hidden in a comment or CDATA comes out as an event of its own
    # when a TAK stream is split at "</event>", past the relay tag and the echo guard.
    if len(_EVENT_OPEN.findall(data)) != 1 or len(_EVENT_CLOSE.findall(data)) != 1:
        return False, "not-one-event"
    if not ev.get("uid"):
        return False, "no-uid"
    pt = ev.find("point")
    if pt is None:
        return False, "no-point"
    try:
        lat, lon = float(pt.get("lat")), float(pt.get("lon"))
    except (TypeError, ValueError):
        return False, "bad-coords"
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return False, "coords-out-of-range"
    try:
        stale = _parse_time(ev.get("stale", ""))
    except ValueError:
        return False, "bad-stale"
    if stale < (time.time() if now is None else now):
        return False, "already-stale"
    return True, ""


def uid_of(data: bytes) -> str:
    try:
        return ET.fromstring(data.strip()).get("uid", "")
    except ET.ParseError:
        return ""


class RateLimiter:
    """Allow at most `max_hz` events per key per second."""

    def __init__(self, max_hz: float = 2.0):
        self.gap = 1.0 / max_hz if max_hz > 0 else 0.0
        self.last = {}
        self._lock = threading.Lock()  # called from several Zenoh callback threads

    def allow(self, key: str, now: float = None) -> bool:
        if self.gap <= 0:
            return True
        now = time.time() if now is None else now
        with self._lock:
            prev = self.last.get(key)
            if prev is not None and now - prev < self.gap:
                return False
            self.last[key] = now
            if len(self.last) > 5000:
                cutoff = now - 60
                self.last = {k: v for k, v in self.last.items() if v > cutoff}
        return True
