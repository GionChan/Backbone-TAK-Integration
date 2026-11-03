import json
import struct
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "relay"))
import backbone_cot as b  # noqa: E402
import cot_guard  # noqa: E402


def pb_track(ident="demo-abc", lat=29.3, lon=47.8, alt=100.0, domain="air"):
    def tag(f, w):
        return bytes([(f << 3) | w])
    d = lambda v: struct.pack("<d", v)  # noqa: E731
    return (tag(1, 2) + bytes([len(ident)]) + ident.encode() + tag(2, 0) + b"\x80\x01" +
            tag(3, 1) + d(lat) + tag(4, 1) + d(lon) + tag(5, 1) + d(alt) +
            tag(8, 2) + bytes([len(domain)]) + domain.encode())


def one(res):
    assert len(res) == 1, res
    return res[0]


def check_valid(xml):
    ok, why = cot_guard.validate_cot(xml)
    assert ok, why
    return ET.fromstring(xml)


class ConvertTests(unittest.TestCase):
    def test_geotrack(self):
        j = {"schema": "goat.geo.track.v1", "id": "synth:900", "label": "900", "lat": 50.01, "lon": 8.36,
             "alt_m": 2222.6, "course_deg": 50.0, "speed_mps": 19.6, "affiliation": "unknown",
             "dimension": "air", "cot_type": None, "descriptor": "SYNTHETIC"}
        src, uid, xml = one(b.convert("x/geo/track/v1/900", json.dumps(j).encode()))
        ev = check_valid(xml)
        self.assertEqual((src, uid, ev.get("type")), ("geotrack", "GEO.synth:900", "a-u-A"))
        self.assertEqual(ev.find("detail/track").get("speed"), "19.6")

    def test_consilium(self):
        j = {"ci_uuid": "u1", "ci_name": "Virtual UGV 1", "location": {"latitude": "51.45", "longitude": "0.235"},
             "device": {"category": "Vehicle", "model": "X"},
             "parameters": [{"name": "speed", "value": 1.5}, {"name": "heading", "value": 187.3}]}
        src, uid, xml = one(b.convert("k", json.dumps(j).encode()))
        ev = check_valid(xml)
        self.assertEqual(ev.get("type"), "a-f-G-E-V")
        self.assertEqual(ev.find("detail/track").get("course"), "187.3")

    def test_mavlink_scaling(self):
        j = {"mavpackettype": "GLOBAL_POSITION_INT", "lat": 393900684, "lon": -71055635, "alt": 300000,
             "hdg": 9000, "vx": 300, "vy": 400, "src_system": 90}
        _, uid, xml = one(b.convert("k", json.dumps(j).encode()))
        ev = check_valid(xml)
        self.assertAlmostEqual(float(ev.find("point").get("lat")), 39.3900684, places=5)
        self.assertEqual(ev.find("detail/track").get("speed"), "5.0")
        self.assertEqual(ev.find("detail/track").get("course"), "90.0")

    def test_hymots_agents_and_sidc(self):
        j = {"agents": [
            {"databaseId": 1, "shortName": "A", "longName": "Brigade", "sidc": "10031000181211040000",
             "location": {"lat": 59.27, "lon": 27.49, "altitude": 70}, "bearing": 0, "speed_km_h": 36},
            {"databaseId": 2, "sidc": "10061000000000000000", "location": {"lat": 0, "lon": 0}},
        ]}
        res = b.convert("k", json.dumps(j).encode())
        self.assertEqual(len(res), 1)  # second has no valid position
        ev = check_valid(res[0][2])
        self.assertEqual(ev.get("type"), "a-f-G-U-C")
        self.assertEqual(ev.find("detail/track").get("speed"), "10.0")
        self.assertEqual(b.sidc_to_type("10061000000000000000"), "a-h-G-U-C")  # hostile land unit
        self.assertEqual(b.sidc_to_type("10030100000000000000"), "a-f-A")      # friendly air (symbol set 01)
        self.assertEqual(b.sidc_to_type("bad"), "a-u-G")

    def test_orion(self):
        j = {"entityId": "e1", "aliases": {"name": "POI"},
             "location": {"position": {"latitudeDegrees": 51.47, "longitudeDegrees": -0.43}}}
        _, uid, xml = one(b.convert("k", json.dumps(j).encode()))
        self.assertEqual(uid, "ORION.e1")
        check_valid(xml)

    def test_protobuf_track(self):
        src, uid, xml = one(b.convert("release/REL-ALL/h/sys/fob/tracks/v1", pb_track()))
        ev = check_valid(xml)
        self.assertEqual((src, uid, ev.get("type")), ("proto", "PB.demo-abc", "a-u-A"))
        self.assertAlmostEqual(float(ev.find("point").get("lon")), 47.8)

    def test_protobuf_on_vendor_site_topic_but_not_ops(self):
        self.assertEqual(one(b.convert("org1/peregrine/alpha-fob", pb_track()))[0], "proto")
        self.assertEqual(b.convert("ops/fabric/footprint/x", pb_track()), [])

    def test_protobuf_without_domain_field(self):
        raw = bytes.fromhex("0a0f706572656772696e652d616c706861" "10ccb4f3ab8c34" "197520 47b42e3b0440".replace(" ", "")
                            + "216762 3a3e299c5240".replace(" ", ""))
        src, uid, xml = one(b.convert("org/peregrine/alpha-fob", raw))
        check_valid(xml)
        self.assertEqual((src, uid), ("proto", "PB.peregrine-alpha"))

    def test_adsb_aircraft(self):
        j = {"kind": "uk-adsb-assessment", "aircraft": [
            {"icao": "010208", "callsign": "MSR795 ", "lat": 52.97, "lon": -1.59, "alt": 13650, "gs": 336.0,
             "track": 328.0, "provider": "opensky"}, {"icao": "bad", "lat": 500, "lon": 0}]}
        src, uid, xml = one(b.convert("org/orion/uk-adsb", json.dumps(j).encode()))
        ev = check_valid(xml)
        self.assertEqual((src, uid, ev.get("type")), ("adsb", "ADSB.010208", "a-n-A-C-F"))
        self.assertAlmostEqual(float(ev.find("point").get("hae")), 4160.5, places=0)

    def test_alert_locations(self):
        j = {"id": "1", "alert_text": "UAVs seen", "event": {"id": "e", "severity": "medium", "tags": ["UAV"],
             "locations": [{"text": "Rivne", "lat": 50.87, "lng": 27.8}, {"text": "none"}]}}
        src, uid, xml = one(b.convert("org/real_time_alerts/x", json.dumps(j).encode()))
        check_valid(xml)
        self.assertEqual((src, uid), ("alerts", "ALERT.e.0"))

    def test_roi_task(self):
        j = {"taskID": "t", "lat": 51.2, "lon": 5.9, "alt": None, "droneId": "2-1",
             "command": "MAV_CMD_DO_SET_ROI_LOCATION"}
        src, uid, xml = one(b.convert("org/anduril/lattice", json.dumps(j).encode()))
        self.assertEqual((src, uid, check_valid(xml).get("type")), ("roi", "ROI.2-1", "b-m-p-s-m"))

    def test_protobuf_only_when_plausible(self):
        self.assertEqual(b.convert("release/x/tracks/v1", pb_track(lat=500.0)), [])
        self.assertEqual(b.convert("release/x/tracks/v1", pb_track(domain="weird")), [])
        self.assertEqual(b.convert("release/x/tracks/v1", b"\n\xff\xff\xff"), [])

    def test_xml_passthrough_and_source_filter(self):
        xml = b'<event uid="a"/>'
        self.assertEqual(one(b.convert("any/key", xml))[0], "xml")
        self.assertEqual(b.convert("any/key", xml, sources=("geotrack",)), [])

    def test_unrecognised_json_and_junk(self):
        self.assertEqual(b.convert("k", b'{"hello": 1}'), [])
        self.assertEqual(b.convert("k", b"[1,2]"), [])
        self.assertEqual(b.convert("k", b"\x00\x01"), [])
        self.assertEqual(b.convert("k", b""), [])


if __name__ == "__main__":
    unittest.main()
