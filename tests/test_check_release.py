"""tools/check_release.py: tag, relay version, CHANGELOG and compose must agree."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import check_release as cr  # noqa: E402


class CheckReleaseTests(unittest.TestCase):
    def test_repository_is_consistent(self):
        self.assertEqual(cr.check(), [])
        self.assertEqual(cr.check(f"v{cr.relay_version()}"), [])

    def test_wrong_tag(self):
        self.assertTrue(cr.check("v0.0.1"))

    def test_changelog_section(self):
        text = "# Changelog\n\n## 2.0.0 - 2027-01-01\n\n- new\n\n## 1.0.0\n\n- old\n"
        self.assertEqual(cr.changelog_section(text), ("2.0.0", "- new"))

    def test_mismatches_are_reported(self):
        with mock.patch.object(cr, "relay_version", return_value="9.9.9"):
            problems = cr.check("v9.9.9")
        self.assertTrue(any("CHANGELOG" in p for p in problems))
        self.assertTrue(any("docker-compose" in p for p in problems))


if __name__ == "__main__":
    unittest.main()
