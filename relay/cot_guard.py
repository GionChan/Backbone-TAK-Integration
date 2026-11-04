"""Sanity checks for CoT XML before it is forwarded to a TAK client.

Other vendors' CoT is forwarded verbatim, so a malformed event must not reach
a TAK client (some have crashed on odd input). Pure functions, no I/O.
"""
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

MAX_BYTES = 64 * 1024


def _parse_time(s: str) -> float:
    s = s.strip()
    fmt = "%Y-%m-%dT%H:%M:%S.%fZ" if "." in s else "%Y-%m-%dT%H:%M:%SZ"
    return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc).timestamp()


def validate_cot(data: bytes, now: float = None):
    """Return (True, "") or (False, reason)."""
    if len(data) > MAX_BYTES:
        return False, "too-large"
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
