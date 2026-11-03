"""Demo sender: the one place demo data enters the backbone.

Scenarios compute positions; this module publishes them. Every message is labelled as
exercise data so nobody mistakes it for a real report:

  <org>/exercise/<scenario>/v1/<uid>   JSON track  {"exercise": true, "classification": "SIMULATED", ...}
  <org>/tak/cot/v1/EXERCISE.<uid>      CoT 2.0 marker, callsign "EXERCISE ...", remarks say SIMULATED

Simulated data never goes to <org>/sensor/v1/** (real telemetry). The TAK relay forwards the
CoT marker to TAK clients like any other vendor's CoT, so the demo exercises the real path.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "relay"))
import zenoh  # noqa: E402

import backbone_cot as bc  # noqa: E402
import goat_connect as gc  # noqa: E402

LABEL = "EFDI exercise inject -- SIMULATED, NOT A REAL THREAT"
EXERCISE_ROOT = f"{gc.ORG}/exercise"
COT_PREFIX = f"{gc.ORG}/tak/cot/v1"


def open_session(name: str):
    """Open a session (real fabric when a bundle is present, else the local router)."""
    conf, is_real = gc.make_config()
    where = f"REAL FABRIC {gc.ROUTER} as {gc.ORG}" if is_real else f"local router {gc.LOCAL_ROUTER}"
    print(f"[{name}] *** SIMULATED / EXERCISE DATA *** -> {where}", flush=True)
    return zenoh.open(conf)


class Sender:
    def __init__(self, session, scenario: str, cot_stale_s: float = 15.0):
        self.session = session
        self.scenario = scenario
        self.cot_stale_s = cot_stale_s
        self._seq = {}

    def topic(self, uid: str) -> str:
        return f"{EXERCISE_ROOT}/{self.scenario}/v1/{uid}"

    def track(self, uid, lat, lon, alt=0.0, heading=0.0, speed_kmh=0.0, phase="",
              cot_type="a-h-A-M-F-Q", lost=False, **extra) -> dict:
        seq = self._seq.get(uid, 0) + 1
        self._seq[uid] = seq
        body = {
            "exercise": True, "classification": "SIMULATED", "label": LABEL, "scenario": self.scenario,
            "source": uid, "type": "hostile-uav", "lat": lat, "lon": lon, "alt": alt,
            "heading": round(float(heading), 1), "speed_kmh": round(float(speed_kmh), 1),
            "phase": phase, "lost": bool(lost), "seq": seq, "ts_ms": int(time.time() * 1000),
        }
        body.update(extra)
        self.session.put(self.topic(uid), json.dumps(body).encode(), encoding=zenoh.Encoding.APPLICATION_JSON)
        if not lost:  # a lost track simply goes stale in TAK
            cot = bc.make_cot(
                uid=f"EXERCISE.{uid}", typ=cot_type, lat=lat, lon=lon, hae=alt, ce=50.0,
                course=heading, speed=float(speed_kmh) / 3.6, callsign=f"EXERCISE {uid}",
                remarks=f"SIMULATED -- {LABEL}. scenario={self.scenario} phase={phase}",
                stale_s=self.cot_stale_s)
            self.session.put(f"{COT_PREFIX}/EXERCISE.{uid}", cot, encoding=zenoh.Encoding.APPLICATION_XML)
        return body
