"""Build TAK-ready Cursor-on-Target 2.0 XML from an edge-AI detection.

The output is what lands on the backbone at  <ORG>/tak/cot/v1/<uid>  and is
forwarded to WinTAK/ATAK by the TAK relay (relay/tak_gateway.py) after validation.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from xml.sax.saxutils import escape


def _attr(value) -> str:
    """escape() for a double-quoted attribute (escape() alone leaves the quote)."""
    return escape(str(value), {'"': "&quot;"})


# class name (lowercase, substring match) -> CoT battle-dimension/function suffix.
# Affiliation letter is prepended from EDGE_COT_AFFIL (h/f/n/u/s...), default h.
_TYPE_MAP = [
    ("uav", "A-M-F-Q"), ("drone", "A-M-F-Q"), ("quad", "A-M-F-Q"),
    ("airplane", "A-M-F"), ("aircraft", "A-M-F"), ("helicopter", "A-M-H"),
    ("person", "G-U-C-I"), ("infantry", "G-U-C-I"),
    ("car", "G-E-V-C"), ("truck", "G-E-V-A"), ("bus", "G-E-V-A"),
    ("motorcycle", "G-E-V-M"), ("vehicle", "G-E-V"),
    ("boat", "S-X"), ("ship", "S-X"), ("vessel", "S-X"),
]
_DEFAULT_SUFFIX = "G"


def cot_type(label: str, affil: str | None = None) -> str:
    a = (affil or os.environ.get("EDGE_COT_AFFIL", "h")).lower()[:1] or "u"
    lab = (label or "").lower()
    suffix = next((s for key, s in _TYPE_MAP if key in lab), _DEFAULT_SUFFIX)
    return f"a-{a}-{suffix}"


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def build_cot(
    *,
    uid: str,
    label: str,
    conf: float,
    lat: float,
    lon: float,
    hae: float = 0.0,
    course: float | None = None,
    speed_ms: float | None = None,
    ce_m: float = 30.0,
    le_m: float = 9999999.0,
    stale_s: int | None = None,
    parent_uid: str | None = None,
    parent_type: str | None = None,
    node_id: str = "edge-ai",
    model: str = "unknown",
    sensor: dict | None = None,
    remarks_extra: str = "",
    affil: str | None = None,
) -> str:
    now = datetime.now(timezone.utc)
    stale = now + timedelta(seconds=stale_s or int(os.environ.get("EDGE_COT_STALE_S", "30")))
    typ = cot_type(label, affil)

    detail = [
        f'<contact callsign="{_attr(uid)}"/>',
        f'<status readiness="true"/>',
        f'<precisionlocation altsrc="CALC" geopointsrc="CALC"/>',
        f'<_flow-tags_ efdi-edge-ai="{_attr(node_id)}/{_attr(model)} '
        f'{_iso(now)}"/>',
    ]
    trk = []
    if course is not None:
        trk.append(f'course="{course:.1f}"')
    if speed_ms is not None:
        trk.append(f'speed="{speed_ms:.1f}"')
    if trk:
        detail.append(f'<track {" ".join(trk)}/>')
    if sensor:
        sat = " ".join(
            f'{k}="{v}"' for k, v in sensor.items() if v is not None
        )
        detail.append(f"<sensor {sat}/>")
    if parent_uid:
        detail.append(
            f'<link uid="{_attr(parent_uid)}" production_time="{_iso(now)}" '
            f'relation="p-p" type="{_attr(parent_type or "a-f-G")}"/>'
        )
    rmk = (
        f"EDGE-AI {label} p={conf:.2f} | node={node_id} model={model} "
        f"| CE~{ce_m:.0f}m {remarks_extra}"
    ).strip()
    detail.append(f"<remarks>{escape(rmk)}</remarks>")

    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<event version="2.0" uid="{_attr(uid)}" type="{_attr(typ)}" how="m-c" '
        f'time="{_iso(now)}" start="{_iso(now)}" stale="{_iso(stale)}">'
        f'<point lat="{lat:.7f}" lon="{lon:.7f}" hae="{hae:.1f}" '
        f'ce="{ce_m:.1f}" le="{le_m:.1f}"/>'
        f'<detail>{"".join(detail)}</detail>'
        "</event>"
    )
