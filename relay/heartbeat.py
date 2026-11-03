"""Mandatory system heartbeat for the EFDI goat fabric.

Publishes <org>/<system>/heartbeat/v1 every `interval` seconds (<= 900) with the body
  {key, system, status, version, sent_at, seq, interval_seconds}
where status is "ok" | "degraded" from a REAL health check (health_fn), never just a timer.
"""
import json
import threading
import time
from datetime import datetime, timezone


def build_body(topic, system, status, version, seq, interval):
    return {
        "key": topic,
        "system": system,
        "status": status,
        "version": version,
        "sent_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "seq": seq,
        "interval_seconds": interval,
    }


class Heartbeat:
    def __init__(self, session, org, system, version="1.0", interval=60.0, health_fn=None,
                 display_name=None, log=print):
        if not (0 < interval <= 900):
            raise ValueError("heartbeat interval must be in (0, 900] seconds")
        self.session = session
        self.topic = f"{org}/{system}/heartbeat/v1"
        self.display_name = display_name or system
        self.version = version
        self.interval = interval
        self.health_fn = health_fn or (lambda: True)
        self.log = log
        self.seq = 0
        self._stop = threading.Event()

    def status(self) -> str:
        try:
            return "ok" if self.health_fn() else "degraded"
        except Exception:  # noqa: BLE001
            return "degraded"

    def beat(self) -> dict:
        self.seq += 1
        body = build_body(self.topic, self.display_name, self.status(), self.version, self.seq, self.interval)
        try:
            self.session.put(self.topic, json.dumps(body).encode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            self.log(f"heartbeat publish failed (seq={self.seq}): {exc}")
        return body

    def _run(self):
        while not self._stop.is_set():
            self.beat()
            self._stop.wait(self.interval)

    def start(self):
        self.log(f"heartbeat: {self.topic} every {self.interval:.0f}s")
        threading.Thread(target=self._run, daemon=True).start()
        return self

    def stop(self):
        self._stop.set()
