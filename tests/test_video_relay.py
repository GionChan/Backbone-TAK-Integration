import sys
import threading
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "relay"))
import video_relay as vr  # noqa: E402


class SafeCamIdTests(unittest.TestCase):
    def test_sanitizes_and_bounds_length(self):
        cam = vr.safe_cam_id("org123/TACTIQL-standardized-video/v1")
        self.assertRegex(cam, r"^[A-Za-z0-9._-]+$")
        self.assertLessEqual(len(cam), 80)

    def test_keeps_suffix_when_too_long(self):
        # RTSP paths / CoT UIDs care most about the part that actually varies between cameras,
        # which for a shared long prefix (org/vendor/topic/...) is at the end.
        long_key = "org123/some/very/long/vendor/prefix/that/keeps/going/" + "x" * 60 + "/camA"
        cam = vr.safe_cam_id(long_key)
        self.assertTrue(cam.endswith("camA"))
        self.assertLessEqual(len(cam), 80)

    def test_never_empty(self):
        self.assertEqual(vr.safe_cam_id("///"), "cam")

    def test_distinct_keys_stay_distinct(self):
        self.assertNotEqual(vr.safe_cam_id("org/video/camA"), vr.safe_cam_id("org/video/camB"))


class VideoCotTests(unittest.TestCase):
    def _parse(self, xml_bytes):
        # video_cot() prepends an XML declaration; ET wants it stripped or it's fine as-is too.
        return ET.fromstring(xml_bytes)

    def test_well_formed_and_carries_video_url(self):
        data = vr.video_cot(uid="video-cam1", callsign="cam1", url="rtsp://10.0.0.5:8554/cam1",
                             path="cam1", port=8554, host="10.0.0.5", now=1000.0)
        root = self._parse(data)
        self.assertEqual(root.tag, "event")
        self.assertEqual(root.get("uid"), "video-cam1")
        video = root.find("./detail/video")
        self.assertIsNotNone(video)
        self.assertEqual(video.get("url"), "rtsp://10.0.0.5:8554/cam1")
        entry = video.find("ConnectionEntry")
        self.assertEqual(entry.get("address"), "10.0.0.5")
        self.assertEqual(entry.get("port"), "8554")
        self.assertEqual(entry.get("protocol"), "rtsp")

    def test_unknown_position_flagged_in_remarks(self):
        data = vr.video_cot(uid="u", callsign="c", url="rtsp://h/p", path="p", port=1, host="h",
                             location_known=False, now=1000.0)
        remarks = self._parse(data).find("./detail/remarks").text
        self.assertIn("unknown", remarks)

    def test_known_position_used(self):
        data = vr.video_cot(uid="u", callsign="c", url="rtsp://h/p", path="p", port=1, host="h",
                             lat=64.1, lon=27.7, location_known=True, now=1000.0)
        point = self._parse(data).find("point")
        self.assertAlmostEqual(float(point.get("lat")), 64.1)
        self.assertAlmostEqual(float(point.get("lon")), 27.7)

    def test_special_characters_escaped(self):
        data = vr.video_cot(uid="u", callsign='cam "1" & <2>', url="rtsp://h/p", path="p",
                             port=1, host="h", now=1000.0)
        # must still parse as well-formed XML despite the raw quotes/ampersand/angle-brackets
        root = self._parse(data)
        self.assertIn('"1"', root.find("./detail/contact").get("callsign"))


class RelayNonBlockingTests(unittest.TestCase):
    """Regression test for the exact bug an end-to-end run against real ffmpeg caught during
    development: ffmpeg's "-rtsp_flags listen" mode does not read stdin at all until an RTSP
    client connects. feed() used to write straight through to the subprocess, so it blocked
    forever the moment the OS pipe buffer filled -- which happens immediately for an unwatched
    camera. Reproduced here with a real subprocess that genuinely never reads its stdin (no
    ffmpeg needed), so this exercises real OS pipe-buffer-full blocking, not a mock of it."""

    def test_feed_does_not_block_when_process_never_drains_stdin(self):
        import subprocess
        import sys
        import time

        never_reads = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                                        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        relay = object.__new__(vr.Relay)  # bypass __init__: skip real ffmpeg spawn
        relay.cam_id, relay.mtx_host, relay.mtx_port, relay.log = "cam", "h", 1, (lambda *a: None)
        relay.ffmpeg, relay.path, relay.push_url = "unused", "cam", "rtsp://h:1/cam"
        relay.last_feed, relay.restarts, relay.dropped = time.time(), 0, 0
        relay.proc = never_reads
        relay._stopping = False
        relay._q = vr.queue.Queue(maxsize=8)
        writer = threading.Thread(target=relay._write_loop, daemon=True)
        writer.start()
        try:
            t0 = time.time()
            for _ in range(300):  # 300 * 8KB = 2.4MB, far past any OS pipe buffer (~64KB typical)
                relay.feed(b"x" * 8192)
            elapsed = time.time() - t0
            self.assertLess(elapsed, 2.0, "feed() blocked -- it must only ever enqueue, never write directly")
            self.assertGreater(relay.dropped, 0, "queue should have overflowed and dropped, proving it filled")
        finally:
            relay.stop()
            never_reads.kill()
            never_reads.wait(timeout=5)
            never_reads.stdin.close()


class _FakeRelay:
    """Stands in for video_relay.Relay: records feeds, no real ffmpeg/subprocess. Constructed
    the same way VideoRelayManager.feed() builds a real one: (cam_id, mtx_host, mtx_port, log)."""

    def __init__(self, cam_id, mtx_host, mtx_port, log=print):
        self.cam_id = cam_id
        self.mtx_host = mtx_host
        self.mtx_port = mtx_port
        self.path = cam_id
        self.push_url = f"rtsp://{mtx_host}:{mtx_port}/{cam_id}"
        self.last_feed = 0.0
        self.fed = []
        self.stopped = False

    def feed(self, data):
        import time
        self.last_feed = time.time()
        self.fed.append(data)

    def status(self):
        return {"cam_id": self.cam_id, "push_url": self.push_url}

    def stop(self):
        self.stopped = True


class VideoRelayManagerTests(unittest.TestCase):
    def _mgr(self, **kw):
        kw.setdefault("public_host", "10.0.0.5")
        kw.setdefault("mtx_port", 8554)
        kw.setdefault("relay_factory", _FakeRelay)
        kw.setdefault("mediamtx_factory", None)  # no real mediamtx needed with a fake relay
        return vr.VideoRelayManager(**kw)

    def test_enabled_with_injected_factory_even_without_real_ffmpeg(self):
        self.assertTrue(self._mgr().enabled)

    def test_feed_creates_one_relay_per_distinct_camera(self):
        mgr = self._mgr()
        self.assertTrue(mgr.feed("org/video/camA", b"x"))
        self.assertTrue(mgr.feed("org/video/camB", b"y"))
        self.assertTrue(mgr.feed("org/video/camA", b"z"))
        self.assertEqual(len(mgr.relays), 2)
        self.assertEqual(mgr.relays[vr.safe_cam_id("org/video/camA")].fed, [b"x", b"z"])

    def test_all_cameras_share_the_same_mediamtx_port(self):
        mgr = self._mgr(mtx_port=8554)
        for i in range(4):
            mgr.feed(f"org/video/cam{i}", b"x")
        ports = {r.mtx_port for r in mgr.relays.values()}
        self.assertEqual(ports, {8554})  # one shared RTSP server, not one port each

    def test_each_camera_gets_its_own_path(self):
        mgr = self._mgr()
        mgr.feed("org/video/camA", b"x")
        mgr.feed("org/video/camB", b"y")
        paths = {r.path for r in mgr.relays.values()}
        self.assertEqual(len(paths), 2)

    def test_due_for_cot_respects_republish_interval(self):
        mgr = self._mgr(republish_s=10.0, idle_s=1000.0)
        mgr.feed("org/video/cam1", b"x")
        due = mgr.due_for_cot(now=100.0)
        self.assertEqual(list(due), [vr.safe_cam_id("org/video/cam1")])
        due_again_too_soon = mgr.due_for_cot(now=105.0)
        self.assertEqual(due_again_too_soon, {})
        due_after_interval = mgr.due_for_cot(now=111.0)
        self.assertEqual(list(due_after_interval), [vr.safe_cam_id("org/video/cam1")])

    def test_idle_camera_is_released(self):
        mgr = self._mgr(idle_s=30.0, republish_s=1000.0)
        mgr.feed("org/video/cam1", b"x")
        relay = next(iter(mgr.relays.values()))
        relay.last_feed = 0.0  # simulate long silence
        mgr.due_for_cot(now=1000.0)
        self.assertEqual(mgr.relays, {})
        self.assertTrue(relay.stopped)
        self.assertTrue(mgr.feed("org/video/cam2", b"y"))  # unaffected: a new camera still works

    def test_status_reports_all_active_relays(self):
        mgr = self._mgr()
        mgr.feed("org/video/cam1", b"x")
        mgr.feed("org/video/cam2", b"y")
        st = mgr.status()
        self.assertEqual(set(st["cameras"]), {vr.safe_cam_id("org/video/cam1"), vr.safe_cam_id("org/video/cam2")})

    def test_stop_all_clears_state(self):
        mgr = self._mgr()
        mgr.feed("org/video/cam1", b"x")
        mgr.stop_all()
        self.assertEqual(mgr.relays, {})
        self.assertEqual(mgr.due_for_cot(now=1e12), {})


class DisabledWithoutFfmpegOrMediaMtxTests(unittest.TestCase):
    def test_real_factories_disabled_when_binaries_missing(self):
        mgr = vr.VideoRelayManager(public_host="h", mtx_port=1)
        if vr.FFMPEG is None or vr.MEDIAMTX is None:
            self.assertFalse(mgr.enabled)
            self.assertFalse(mgr.feed("org/video/cam1", b"x"))
            self.assertEqual(mgr.relays, {})
        else:
            self.skipTest("ffmpeg and mediamtx are both present on this machine's PATH; nothing to assert here")


if __name__ == "__main__":
    unittest.main()
