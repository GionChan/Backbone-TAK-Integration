import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "relay"))
import stream_view as sv  # noqa: E402

ORG = "0123456789abcdef0123456789abcdef"


class StreamViewTests(unittest.TestCase):
    def test_grouping(self):
        self.assertEqual(sv.group_of("orgA/sys/topic/v1/extra/id"), "orgA/sys/topic")
        self.assertEqual(sv.group_of("release/REL-ALL/h/sys/fob/tracks/v1"), "release/REL-ALL/h/sys")
        self.assertEqual(sv.group_of("short/key"), "short/key")

    def test_kinds(self):
        self.assertEqual(sv.kind_of(bytes([0xFF, 0xD8, 0xFF, 0xE0])), "jpeg")
        self.assertEqual(sv.kind_of(b"<event/>"), "xml")
        self.assertEqual(sv.kind_of(b'{"a":1}'), "json")
        self.assertEqual(sv.kind_of(bytes([0x47, 0x40, 0x00])), "video-ts")
        self.assertEqual(sv.kind_of(b"x", hint="video/binary"), "video/binary")

    def test_rates_own_flag_and_tak(self):
        st = sv.StreamStats(ORG)
        t0 = 1000.0
        for i in range(20):
            st.record(f"{ORG}/tak/cot/v1/u{i}", 400, b"<event", ("xml",), now=t0 + i * 0.5)
        for i in range(5):
            st.record("vendor/sys/track/v1/x", 100, b'{"lat": 1}', (), now=t0 + i * 2)
        snap = st.snapshot(now=t0 + 10)
        rows = {r["group"]: r for r in snap["streams"]}
        own = rows[f"{ORG}/tak/cot"]
        self.assertTrue(own["own"])
        self.assertEqual(own["tak"], {"xml": 20})
        self.assertAlmostEqual(own["msg_per_s"], 2.0, delta=0.3)
        self.assertFalse(rows["vendor/sys/track"]["own"])
        self.assertEqual(rows["vendor/sys/track"]["kind"], "json")
        self.assertIn("lat", rows["vendor/sys/track"]["sample"])

    def test_idle_groups_dropped_and_cap(self):
        st = sv.StreamStats(ORG)
        st.record("a/b/c/d", 1, b"x", now=0)
        self.assertEqual(st.snapshot(now=sv.IDLE_DROP_S + 5)["groups"], 0)
        for i in range(sv.MAX_GROUPS + 50):
            st.record(f"o{i}/s/t/x", 1, b"x", now=1)
        self.assertEqual(st.snapshot(now=2)["groups"], sv.MAX_GROUPS)


try:
    import PIL  # noqa: F401  optional dependency (relay/requirements.txt)
    HAVE_PIL = True
except ImportError:
    HAVE_PIL = False


@unittest.skipUnless(HAVE_PIL, "pillow not installed (optional)")
class ExtractImageTests(unittest.TestCase):
    def _jpeg(self):
        import io
        from PIL import Image
        b = io.BytesIO()
        Image.new("RGB", (16, 16), (1, 2, 3)).save(b, "JPEG")
        return b.getvalue()

    def test_raw_jpeg_and_json_with_nested_base64(self):
        import base64
        import json
        j = self._jpeg()
        self.assertEqual(sv.extract_image(j), j)
        big = base64.b64encode(j * 40).decode()  # long enough to be considered; first bytes are a JPEG
        msg = json.dumps({"sensor": "x", "data": {"keyframe": big, "n": 3}}).encode()
        self.assertTrue(sv.extract_image(msg).startswith(bytes([0xFF, 0xD8, 0xFF])))

    def test_no_image(self):
        self.assertIsNone(sv.extract_image(b'{"a": 1}'))
        self.assertIsNone(sv.extract_image(b"<event/>"))
        self.assertIsNone(sv.video_frame_jpeg(b"not a stream"))


if __name__ == "__main__":
    unittest.main()
