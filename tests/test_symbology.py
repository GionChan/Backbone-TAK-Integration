import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "relay"))
import symbology as s  # noqa: E402


def t(text="", **kw):
    return s.cot_type(text=text, **kw)[0]


class SymbologyTests(unittest.TestCase):
    def test_own_telemetry_types(self):
        self.assertEqual(t("hostile-uav hostile-uav-00", default_dim="A"), "a-h-A-M-F-Q")

    def test_unknown_is_never_hostile(self):
        self.assertEqual(t("something"), "a-u-G")
        self.assertEqual(t("", dimension="air"), "a-u-A")

    def test_explicit_affiliation_beats_text_and_sidc(self):
        self.assertEqual(t("friendly drone", explicit_affiliation="hostile"), "a-h-A-M-F-Q")
        self.assertEqual(t("hostile drone", sidc="10031000000000000000"), "a-f-A-M-F-Q")  # SIDC 3 = friend

    def test_units_vs_equipment(self):
        self.assertEqual(t("3rd Tank Battalion"), "a-u-G-U-C-A")
        self.assertEqual(t("T-90 tank"), "a-u-G-E-V-A-T")
        self.assertEqual(t("Motorized Brigade", sidc="10031000181211040000"), "a-f-G-U-C-I")
        self.assertEqual(t("Artillery Regiment"), "a-u-G-U-C-F")
        self.assertEqual(t("Combat Service Support Brigade"), "a-u-G-U-S")

    def test_air_ground_sea(self):
        self.assertEqual(t("Mi-8 helicopter"), "a-u-A-M-H")
        self.assertEqual(t("fighter jet"), "a-u-A-M-F")
        self.assertEqual(t("cargo ship"), "a-u-S-X")
        self.assertEqual(t("frigate"), "a-u-S-C-L")
        self.assertEqual(t("robocar UGV"), "a-u-G-E-V")
        self.assertEqual(t("Virtual UGV 1 Vehicle", default_affiliation="f"), "a-f-G-E-V")

    def test_sidc_alone(self):
        self.assertEqual(t("", sidc="10061000000000000000"), "a-h-G-U-C")
        self.assertEqual(t("", sidc="10030100000000000000"), "a-f-A")
        self.assertEqual(t("", sidc="10033000000000000000"), "a-f-S")

    def test_kinematics_fallback(self):
        self.assertEqual(t("track 900", hae=2200, speed_mps=200), "a-u-A")
        self.assertEqual(t("track 5", hae=10, speed_mps=3), "a-u-G")

    def test_source_type_wins(self):
        self.assertEqual(t("whatever", forced_type="a-h-A-M-F-Q"), "a-h-A-M-F-Q")
        self.assertEqual(t("drone", forced_type="junk"), "a-u-A-M-F-Q")  # invalid forced type ignored

    def test_no_false_friend_from_common_words(self):
        self.assertEqual(s.affiliation(text="Sam owns his own vehicle"), "u")


if __name__ == "__main__":
    unittest.main()
