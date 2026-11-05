import io
import sys
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "relay"))
import gateway_core as core  # noqa: E402

EV = b'<event version="2.0" uid="a" type="a-f-G" time="t" start="t" stale="t"><point lat="1" lon="2" hae="0" ce="1" le="1"/></event>'


class CoreTests(unittest.TestCase):
    def test_split_two_events_and_partial(self):
        buf = bytearray(EV + b"\n" + EV + EV[:30])
        out = core.split_cot_stream(buf)
        self.assertEqual(len(out), 2)
        self.assertEqual(bytes(buf), EV[:30])
        buf.extend(EV[30:])
        self.assertEqual(len(core.split_cot_stream(buf)), 1)
        self.assertEqual(len(buf), 0)

    def test_xml_declaration_kept(self):
        buf = bytearray(b'<?xml version="1.0"?>' + EV)
        (doc,) = core.split_cot_stream(buf)
        self.assertTrue(doc.startswith(b"<?xml"))

    def test_garbage_is_bounded(self):
        buf = bytearray(b"x" * (core.MAX_STREAM_BUF + 1))
        core.split_cot_stream(buf)
        self.assertEqual(len(buf), 0)

    def test_prometheus(self):
        t = core.prometheus_text({'c_total{a="b"}': 3}, {"g": 1})
        self.assertIn('c_total{a="b"} 3', t)
        self.assertIn("# TYPE g gauge", t)

    def test_prometheus_one_type_line_per_metric(self):
        t = core.prometheus_text({'d_total{r="a"}': 1, 'd_total{r="b"}': 2}, {})
        self.assertEqual(t.count("# TYPE d_total counter"), 1)
        self.assertLess(t.index("# TYPE d_total"), t.index('d_total{r="a"}'))

    def test_data_package(self):
        z = zipfile.ZipFile(io.BytesIO(core.atak_data_package("10.0.0.5", 8087)))
        self.assertIn("MANIFEST/manifest.xml", z.namelist())
        self.assertIn("10.0.0.5:8087:tcp", z.read("EFDI/efdi-backbone.pref").decode())


if __name__ == "__main__":
    unittest.main()
