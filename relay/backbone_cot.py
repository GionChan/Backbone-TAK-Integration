"""Turn whatever positional data other vendors publish on the backbone into CoT 2.0 XML.

Pure functions (no I/O). Recognised shapes (found on the EFDI fabric):
  xml        any CoT <event> on any key (forwarded as is)
  geotrack   JSON  schema "goat.geo.track.v1"
  consilium  JSON  {"ci_uuid", "location": {"latitude","longitude"}, ...}
  mavlink    JSON  {"mavpackettype": "GLOBAL_POSITION_INT", lat/lon in 1e-7 deg}
  hymots     JSON  {"agents": [{"location": {lat, lon}, "sidc", ...}]}   (order of battle snapshot)
  orion      JSON  {"entityId", "location": {"position": {"latitudeDegrees", ...}}}
  adsb       JSON  {"kind": "uk-adsb-assessment", "aircraft": [{icao, callsign, lat, lon, alt ft, gs kt, track}]}
  alerts     JSON  {"alert_text", "event": {"locations": [{lat, lng, text}], severity}}   (news/threat alerts)
  roi        JSON  {"lat", "lon", "command": "MAV_CMD_DO_SET_ROI_LOCATION", "droneId"}    (region of interest)
  proto      protobuf demo tracks (release/** and <org>/<vendor>/<site> topics): id(1) ts(2) lat(3) lon(4) alt(5) ... domain(8).
             Schema inferred from the wire format, not documented: remarks say so.
Each converter returns a list of (source_name, uid, cot_xml_bytes).
"""
import json
import struct
import time
from xml.sax.saxutils import escape

import symbology

ALL_SOURCES = ("xml", "geotrack", "consilium", "mavlink", "hymots", "orion", "adsb", "alerts", "roi", "proto")


def _iso(t: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(t))


def _attr(value) -> str:
    """escape() for a double-quoted XML attribute: escape() alone only handles &<>, not the '"'
    that would otherwise break the parse if it's in the value -- callsign/uid here can be
    arbitrary vendor-supplied text (ADSB transponder callsign, hymots agent name, ...)."""
    return escape(str(value), {'"': "&quot;"})


def make_cot(uid, typ, lat, lon, hae=0.0, ce=50.0, course=None, speed=None,
             callsign=None, remarks="", stale_s=30, how="m-g", now=None) -> bytes:
    now = time.time() if now is None else now
    track = ""
    if course is not None and speed is not None:
        track = f'<track course="{float(course) % 360:.1f}" speed="{max(float(speed), 0):.1f}"/>'
    detail = (f'<contact callsign="{_attr(callsign or uid)}"/>{track}'
              f'<remarks>{escape(remarks)}</remarks>')
    xml = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           f'<event version="2.0" uid="{_attr(uid)}" type="{_attr(typ)}" how="{_attr(how)}" '
           f'time="{_iso(now)}" start="{_iso(now)}" stale="{_iso(now + stale_s)}">'
           f'<point lat="{float(lat):.7f}" lon="{float(lon):.7f}" hae="{float(hae):.1f}" '
           f'ce="{float(ce):.1f}" le="9999999.0"/><detail>{detail}</detail></event>')
    return xml.encode()


def _valid(lat, lon) -> bool:
    return isinstance(lat, (int, float)) and isinstance(lon, (int, float)) and \
        -90 <= lat <= 90 and -180 <= lon <= 180 and not (lat == 0 and lon == 0)


def sidc_to_type(sidc: str) -> str:
    return symbology.cot_type(sidc=sidc)[0]


def _t(text="", **kw):
    """(cot type, remark suffix) from symbology."""
    typ, basis = symbology.cot_type(text=text, **kw)
    return typ, f" [type:{basis}]"


# ---- converters ---------------------------------------------------------------
def from_geotrack(j):
    if j.get("schema") != "goat.geo.track.v1" or not _valid(j.get("lat"), j.get("lon")):
        return []
    text = f"{j.get('label', '')} {j.get('kind', '')} {(j.get('source') or {}).get('node', '')}"
    typ, basis = _t(text, explicit_affiliation=j.get("affiliation"), dimension=j.get("dimension"),
                    hae=j.get("alt_m"), speed_mps=j.get("speed_mps"), forced_type=j.get("cot_type"))
    uid = f"GEO.{j.get('id')}"
    rem = f"{j.get('descriptor', '')} src={(j.get('source') or {}).get('sensor', '?')}{basis}"
    return [("geotrack", uid, make_cot(uid, typ, j["lat"], j["lon"], j.get("alt_m") or 0, j.get("ce_m") or 100,
                                      j.get("course_deg"), j.get("speed_mps"), j.get("label"), rem))]


def from_consilium(j):
    loc = j.get("location") or {}
    try:
        lat, lon = float(loc["latitude"]), float(loc["longitude"])
    except (KeyError, TypeError, ValueError):
        return []
    if "ci_uuid" not in j or not _valid(lat, lon):
        return []
    params = {p.get("name"): p.get("value") for p in j.get("parameters", []) if isinstance(p, dict)}
    dev = j.get("device") or {}
    uid = f"CONSILIUM.{j['ci_uuid']}"
    text = f"{j.get('ci_name', '')} {dev.get('category', '')} {dev.get('type', '')} {dev.get('model', '')}"
    typ, basis = _t(text, default_affiliation="f", default_dim="G", speed_mps=params.get("speed"))
    rem = f"{dev.get('category', '')} {dev.get('model', '')} status={params.get('status', '?')}{basis}"
    return [("consilium", uid, make_cot(uid, typ, lat, lon, 0, 25, params.get("heading"),
                                        params.get("speed"), j.get("ci_name"), rem))]


def from_mavlink(j):
    if j.get("mavpackettype") != "GLOBAL_POSITION_INT":
        return []
    lat, lon = j.get("lat", 0) / 1e7, j.get("lon", 0) / 1e7
    if not _valid(lat, lon):
        return []
    uid = f"MAV.{j.get('src_system', 0)}"
    vx, vy = j.get("vx", 0) / 100.0, j.get("vy", 0) / 100.0
    speed = (vx * vx + vy * vy) ** 0.5
    typ, basis = _t("uav", default_affiliation="f")
    return [("mavlink", uid, make_cot(uid, typ, lat, lon, j.get("alt", 0) / 1000.0, 10,
                                      j.get("hdg", 0) / 100.0, speed, uid, "MAVLink GLOBAL_POSITION_INT" + basis))]


def from_hymots(j):
    out = []
    for a in j.get("agents", []) if isinstance(j.get("agents"), list) else []:
        loc = a.get("location") or {}
        if not _valid(loc.get("lat"), loc.get("lon")):
            continue
        uid = f"HYMOTS.{a.get('databaseId')}"
        text = f"{a.get('longName', '')} {a.get('shortName', '')}"
        typ, basis = _t(text, sidc=a.get("sidc"), dimension=a.get("agentTypeName"), hae=loc.get("altitude"),
                        speed_mps=(a.get("speed_km_h") or 0) / 3.6)
        rem = f"{a.get('longName', '')} [{a.get('agentTypeName', '')}] sidc={a.get('sidc', '')}{basis}"
        out.append(("hymots", uid, make_cot(uid, typ, loc["lat"], loc["lon"],
                                            loc.get("altitude") or 0, 100, a.get("bearing"),
                                            (a.get("speed_km_h") or 0) / 3.6, a.get("shortName"), rem,
                                            stale_s=60)))
    return out


def from_orion(j):
    pos = ((j.get("location") or {}).get("position")) or {}
    lat, lon = pos.get("latitudeDegrees"), pos.get("longitudeDegrees")
    if "entityId" not in j or not _valid(lat, lon):
        return []
    uid = f"ORION.{j['entityId']}"
    name = (j.get("aliases") or {}).get("name")
    rem = f"{j.get('description', '')} {(j.get('ontology') or {}).get('specificType', '')}"
    typ, basis = _t(f"{rem} {name or ''}")
    return [("orion", uid, make_cot(uid, typ, lat, lon, 0, 100, callsign=name, remarks=rem + basis))]


def from_adsb(j):
    if j.get("kind") != "uk-adsb-assessment" or not isinstance(j.get("aircraft"), list):
        return []
    out = []
    for a in j["aircraft"]:
        if not isinstance(a, dict) or not _valid(a.get("lat"), a.get("lon")):
            continue
        uid = f"ADSB.{a.get('icao')}"
        call = (a.get("callsign") or a.get("icao") or "").strip()
        alt_m = (a["alt"] * 0.3048) if isinstance(a.get("alt"), (int, float)) else 0.0
        kt = a.get("gs")
        spd = kt * 0.514444 if isinstance(kt, (int, float)) else None
        rem = f"ADS-B via {a.get('provider', '?')} alt={a.get('alt')}ft gs={kt}kt"
        out.append(("adsb", uid, make_cot(uid, "a-n-A-C-F", a["lat"], a["lon"], alt_m, 200,
                                          a.get("track"), spd, call, rem, stale_s=120)))
    return out


def from_alert(j):
    ev = j.get("event")
    if not isinstance(ev, dict) or "alert_text" not in j:
        return []
    out = []
    head = str(ev.get("headline") or j["alert_text"])[:120]
    sev = ev.get("severity", "?")
    for i, loc in enumerate(ev.get("locations") or []):
        if not isinstance(loc, dict) or not _valid(loc.get("lat"), loc.get("lng")):
            continue
        uid = f"ALERT.{ev.get('id', j.get('id'))}.{i}"
        rem = f"[{sev}] {j['alert_text']} ({loc.get('text', '')}) tags={','.join(ev.get('tags') or [])}"
        out.append(("alerts", uid, make_cot(uid, "a-u-G", loc["lat"], loc["lng"], 0, 5000, callsign=head,
                                            remarks=rem[:600], stale_s=1800)))
    return out


def from_roi(j):
    if not str(j.get("command", "")).endswith("ROI_LOCATION") or not _valid(j.get("lat"), j.get("lon")):
        return []
    uid = f"ROI.{j.get('droneId')}"
    return [("roi", uid, make_cot(uid, "b-m-p-s-m", j["lat"], j["lon"], j.get("alt") or 0, 20,
                                  callsign=f"ROI drone {j.get('droneId')}",
                                  remarks=f"{j['command']} task={j.get('taskID')}", stale_s=300))]


_JSON_CONVERTERS = {
    "geotrack": from_geotrack, "consilium": from_consilium, "mavlink": from_mavlink,
    "hymots": from_hymots, "orion": from_orion,
    "adsb": from_adsb, "alerts": from_alert, "roi": from_roi,
}


# ---- minimal protobuf wire reader (for the inferred demo track schema) ---------
def _varint(b, i):
    shift = val = 0
    while i < len(b):
        c = b[i]
        i += 1
        val |= (c & 0x7F) << shift
        if not c & 0x80:
            return val, i
        shift += 7
        if shift > 63:
            break
    raise ValueError("bad varint")


def _wire_fields(b: bytes) -> dict:
    i, out = 0, {}
    while i < len(b):
        tag, i = _varint(b, i)
        field, wt = tag >> 3, tag & 7
        if wt == 0:
            v, i = _varint(b, i)
        elif wt == 1:
            v, i = struct.unpack("<d", b[i:i + 8])[0], i + 8
        elif wt == 5:
            v, i = struct.unpack("<f", b[i:i + 4])[0], i + 4
        elif wt == 2:
            n, i = _varint(b, i)
            v, i = b[i:i + n], i + n
        else:
            raise ValueError("unsupported wire type")
        out.setdefault(field, v)
    return out


def from_proto_track(key: str, b: bytes):
    if not b or b[0] != 0x0A or len(b) > 512:
        return []
    try:
        f = _wire_fields(b)
        ident, lat, lon = f[1].decode("ascii"), f[3], f[4]
        domain = f.get(8, b"").decode("ascii")
    except (KeyError, ValueError, UnicodeDecodeError, struct.error):
        return []
    if not (isinstance(lat, float) and isinstance(lon, float) and _valid(lat, lon)):
        return []
    if domain and domain not in ('air', 'ground', 'land', 'surface', 'sea', 'subsurface', 'space', 'maritime'):
        return []
    parts = key.split("/")
    src = "/".join(parts[-5:-1]) if len(parts) > 5 else key
    uid = f"PB.{ident}"
    alt = f.get(5) if isinstance(f.get(5), float) else 0.0
    typ, basis = _t(ident, dimension=domain or None)
    return [("proto", uid, make_cot(uid, typ, lat, lon, alt, 200, callsign=ident,
                                    remarks=f"protobuf track (schema inferred, undocumented) via {src}{basis}"))]


# ---- entry point ---------------------------------------------------------------
def convert(key: str, payload: bytes, sources=ALL_SOURCES, max_json=2_000_000):
    """Return [(source, uid, cot_xml_bytes)] for a backbone sample (empty if not recognised)."""
    if not payload:
        return []
    head = payload.lstrip()[:1]
    if head == b"<":
        return [("xml", "", payload)] if "xml" in sources else []
    if head == b"{" and len(payload) <= max_json:
        try:
            j = json.loads(payload)
        except ValueError:
            return []
        if not isinstance(j, dict):
            return []
        out = []
        for name, fn in _JSON_CONVERTERS.items():
            if name in sources:
                out = fn(j)
                if out:
                    return out
        return []
    if payload[:1] == b"\n" and "proto" in sources and not key.startswith("ops/"):
        return from_proto_track(key, payload)
    return []
