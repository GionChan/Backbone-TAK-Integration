import sys
import time
import unittest
import unittest.mock
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "relay"))
import cot_guard as g  # noqa: E402


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def event(lat="50.7", lon="-2.4", stale_s=30, uid="u1", tag="event", extra=""):
    now = datetime.now(timezone.utc)
    return (f'<?xml version="1.0"?><{tag} version="2.0" uid="{uid}" type="a-h-A" '
            f'time="{iso(now)}" start="{iso(now)}" stale="{iso(now + timedelta(seconds=stale_s))}">'
            f'{extra}<point lat="{lat}" lon="{lon}" hae="0" ce="1" le="1"/></{tag}>').encode()


class GuardTests(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(g.validate_cot(event()), (True, ""))

    def test_rejects_garbage_and_wrong_root(self):
        self.assertEqual(g.validate_cot(b"<notxml")[1], "not-xml")
        self.assertEqual(g.validate_cot(event(tag="other"))[1], "not-event")

    def test_rejects_bad_coords(self):
        self.assertEqual(g.validate_cot(event(lat="91"))[1], "coords-out-of-range")
        self.assertEqual(g.validate_cot(event(lat="abc"))[1], "bad-coords")

    def test_rejects_stale_and_no_uid(self):
        self.assertEqual(g.validate_cot(event(stale_s=-5))[1], "already-stale")
        self.assertEqual(g.validate_cot(event(uid=""))[1], "no-uid")

    def test_rejects_dtd_and_oversize(self):
        self.assertEqual(g.validate_cot(b'<!DOCTYPE x [<!ENTITY a "b">]>' + event())[1], "dtd-not-allowed")
        self.assertEqual(g.validate_cot(event(extra="<x>" + "a" * 70000 + "</x>"))[1], "too-large")

    def test_rejects_non_utf8(self):
        dtd = '<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE event [<!ENTITY e "x">]>'
        for data in (dtd.encode("utf-16") + event(),           # BOM
                     dtd.encode("utf-16-le"),                  # no BOM: NUL bytes
                     event().replace(b'version="1.0"?>', b'version="1.0" encoding="UTF-16"?>', 1)):
            self.assertEqual(g.validate_cot(data)[1], "not-utf8")
        utf8 = event().replace(b'version="1.0"?>', b'version="1.0" encoding="UTF-8"?>', 1)
        self.assertEqual(g.validate_cot(utf8), (True, ""))

    def test_exactly_one_event(self):
        # A second event hidden in a comment, CDATA or a processing instruction would come out as an
        # event of its own when a stream is split at "</event>".
        hidden = event(uid="VICTIM").split(b"?>", 1)[1].decode()
        self.assertEqual(g.validate_cot(f"<!-- {hidden} -->{hidden}".replace('"VICTIM"', '"decoy"', 1)
                                        .encode())[1], "not-one-event")
        for wrap in (f"<!-- {hidden} -->", f"<![CDATA[{hidden}]]>", f"<?pi {hidden} ?>"):
            self.assertEqual(g.validate_cot(event(extra=f"<detail>{wrap}</detail>"))[1], "not-one-event")

    def test_rejects_dtd_after_padding(self):
        # A long comment first must not push the DTD past the check.
        padded = b"<!--" + b"x" * 5000 + b'--><!DOCTYPE event [<!ENTITY e "x">]>' + event()
        self.assertEqual(g.validate_cot(padded)[1], "dtd-not-allowed")

    def test_rate_limiter_forgets_idle_keys_and_is_bounded(self):
        r = g.RateLimiter(2)
        for i in range(1000):
            r.allow(f"k{i}", 1000.0)
        r.allow("late", 1100.0)                      # everything else idle for 100 s
        self.assertEqual(list(r.last), ["late"])
        with unittest.mock.patch.object(g.RateLimiter, "MAX_KEYS", 10):
            for i in range(50):
                r.allow(f"n{i}", 1100.5)
            self.assertEqual(len(r.last), 10)

    def test_rate_limiter(self):
        r = g.RateLimiter(2)
        t = time.time()
        self.assertTrue(r.allow("a", t))
        self.assertFalse(r.allow("a", t + 0.1))
        self.assertTrue(r.allow("b", t + 0.1))
        self.assertTrue(r.allow("a", t + 0.6))


if __name__ == "__main__":
    unittest.main()
