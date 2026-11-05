"""Unit tests for relay/tak_gateway.py behaviour that has no I/O beyond loopback sockets."""
import json
import os
import socket
import sys
import threading
import time
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "relay"))
try:
    import tak_gateway as gw
except ImportError as exc:  # eclipse-zenoh not installed
    raise unittest.SkipTest(f"tak_gateway not importable: {exc}")
import cot_guard  # noqa: E402


class _Sample:
    def __init__(self, body: dict):
        self.payload = mock.Mock(to_bytes=lambda: json.dumps(body).encode())


class _Capture:
    name = "capture"

    def __init__(self):
        self.sent = []

    def send(self, data):
        self.sent.append(data)

    def status(self):
        return {"name": self.name, "connected": True}


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class TelemetryTests(unittest.TestCase):
    def setUp(self):
        self.out = _Capture()
        gw.OUTPUTS[:] = [self.out]

    def tearDown(self):
        gw.OUTPUTS[:] = []

    def test_markup_in_payload_is_escaped(self):
        data = gw.telemetry_to_cot({"source": 'x"/><evil a="', "lat": 60.1, "lon": 24.9, "phase": "<b>"})
        ok, reason = cot_guard.validate_cot(data)
        self.assertTrue(ok, reason)
        self.assertEqual(ET.fromstring(data.split(b"?>", 1)[1]).get("uid"), 'x"-><evil a="')

    def test_valid_telemetry_is_dispatched(self):
        gw.on_telemetry(_Sample({"source": "uav-1", "lat": 60.1, "lon": 24.9, "alt": 100}))
        self.assertEqual(len(self.out.sent), 1)

    def test_lost_track_still_reaches_tak(self):
        # "lost" is stale on purpose so TAK removes the track; validation must not drop it.
        gw.on_telemetry(_Sample({"source": "uav-1", "lat": 60.1, "lon": 24.9, "lost": True}))
        self.assertEqual(len(self.out.sent), 1)

    def test_bad_telemetry_is_counted_not_raised(self):
        gw.on_telemetry(_Sample({"source": "uav-1", "lat": None, "lon": 24.9}))
        self.assertEqual(self.out.sent, [])


import backbone_cot as bc  # noqa: E402


class IngestTests(unittest.TestCase):
    """TAK -> backbone: only the operator's own local devices reach the backbone."""

    def setUp(self):
        self.session = mock.Mock()
        gw.SESSION[0], gw.INGEST[0] = self.session, True
        gw._forwarded.clear()
        gw.COUNTERS.clear()
        limiter = mock.patch.object(gw, "_pli_limiter", cot_guard.RateLimiter(1.0))
        limiter.start()
        self.addCleanup(limiter.stop)

    def tearDown(self):
        gw.SESSION[0], gw.INGEST[0] = None, False
        gw._forwarded.clear()
        gw.OUTPUTS[:] = []

    @staticmethod
    def _pli(uid):
        return bc.make_cot(uid, "a-f-G-U-C", 60.1, 24.9, callsign=uid)

    def _published(self):
        return [c.args[0] for c in self.session.put.call_args_list]

    def test_local_device_is_published(self):
        gw.ingest_event(self._pli("ANDROID-own1"), "udp_in@127.0.0.1")
        self.assertEqual(self._published(), [f"{gw.gc.ORG}/tak/pli/v1/ANDROID-own1"])

    def test_without_allowlist_only_this_machine_publishes(self):
        gw.ingest_event(self._pli("SPOOF-1"), "udp_in@192.168.1.50")
        gw.ingest_event(self._pli("SPOOF-2"), "tcp_server:8087@10.0.0.9:50000")
        gw.ingest_event(self._pli("ANDROID-own1"), "tcp_server:8087@127.0.0.1:50001")
        self.assertEqual(self._published(), [f"{gw.gc.ORG}/tak/pli/v1/ANDROID-own1"])
        self.assertEqual(gw.COUNTERS['gateway_ingest_dropped_total{reason="not-loopback"}'], 2)

    def test_allowlist_admits_named_devices_from_the_network(self):
        with mock.patch.object(gw, "INGEST_UIDS", frozenset({"ANDROID-own1"})):
            gw.ingest_event(self._pli("ANDROID-own1"), "udp_in@192.168.1.50")
        self.assertEqual(self._published(), [f"{gw.gc.ORG}/tak/pli/v1/ANDROID-own1"])

    def test_tak_server_users_are_not_published(self):
        gw.ingest_event(self._pli("ANDROID-other"), "tcp_client:tak:8089", "server")
        self.assertEqual(self._published(), [])
        self.assertEqual(gw.COUNTERS['gateway_ingest_dropped_total{reason="not-local"}'], 1)

    def test_server_ingest_needs_explicit_opt_in(self):
        with mock.patch.object(gw, "INGEST_FROM", frozenset({"local", "server"})):
            gw.ingest_event(self._pli("ANDROID-srv2"), "tcp_client:tak:8089", "server")
        self.assertEqual(len(self._published()), 1)

    def test_allowlist_limits_to_named_devices(self):
        with mock.patch.object(gw, "INGEST_UIDS", frozenset({"ANDROID-own1"})):
            gw.ingest_event(self._pli("ANDROID-own1"), "udp_in@127.0.0.1")
            gw.ingest_event(self._pli("ANDROID-stranger"), "udp_in@127.0.0.1")
        self.assertEqual(self._published(), [f"{gw.gc.ORG}/tak/pli/v1/ANDROID-own1"])
        self.assertEqual(gw.COUNTERS['gateway_ingest_dropped_total{reason="not-allowed"}'], 1)

    def test_markers_the_relay_sent_are_not_echoed_back(self):
        gw.OUTPUTS[:] = [_Capture()]
        event = bc.make_cot("vendor-x.track-7", "a-f-G-U-C", 60.1, 24.9, now=1_800_000_000)
        gw.dispatch(event)                                   # backbone -> TAK
        gw.ingest_event(event, "udp_in@127.0.0.1")           # a TAK client forwards it back untagged
        self.assertEqual(self._published(), [])
        self.assertEqual(gw.COUNTERS['gateway_ingest_dropped_total{reason="echo"}'], 1)

    def test_fresh_own_position_is_published_after_a_mirrored_copy(self):
        # Someone mirrored an older position of our device back via the backbone; the relay sent it
        # to TAK. The device's next, newer position must still be published.
        gw.OUTPUTS[:] = [_Capture()]
        gw.dispatch(bc.make_cot("ANDROID-own1", "a-f-G-U-C", 60.1, 24.9, now=time.time() - 3))
        gw.ingest_event(bc.make_cot("ANDROID-own1", "a-f-G-U-C", 60.1, 24.9), "udp_in@127.0.0.1")
        self.assertEqual(self._published(), [f"{gw.gc.ORG}/tak/pli/v1/ANDROID-own1"])

    def test_lan_needs_the_allowlist(self):
        with mock.patch.object(gw, "INGEST_FROM", frozenset({"local", "lan"})):
            gw.ingest_event(self._pli("ANDROID-neighbour"), "multicast@10.0.0.9", "lan")
            self.assertEqual(self._published(), [])
            with mock.patch.object(gw, "INGEST_UIDS", frozenset({"ANDROID-own1"})):
                gw.ingest_event(self._pli("ANDROID-own1"), "multicast@10.0.0.5", "lan")
        self.assertEqual(self._published(), [f"{gw.gc.ORG}/tak/pli/v1/ANDROID-own1"])

    def test_events_another_relay_sent_are_not_published(self):
        gw.ingest_event(gw.tag(self._pli("vendor-y.track-1")), "multicast@10.0.0.7", "local")
        self.assertEqual(self._published(), [])
        self.assertEqual(gw.COUNTERS['gateway_ingest_dropped_total{reason="relayed"}'], 1)

    def test_tcp_client_link_reads_as_server(self):
        a, b = socket.socketpair()
        with mock.patch.object(gw, "ingest_event") as ing:
            b.sendall(self._pli("ANDROID-other"))
            b.close()
            gw._reader(a, "tcp_client:x", "server")
        self.assertEqual(ing.call_args.args[2], "server")
        a.close()


class TagTests(unittest.TestCase):
    def test_self_closing_detail_with_space(self):
        tagged = gw.tag(b'<event uid="u5"><point lat="1" lon="1"/><detail /></event>')
        self.assertEqual(ET.fromstring(tagged).findall("detail")[0].find("__efdi_relay").tag, "__efdi_relay")
        self.assertEqual(len(ET.fromstring(tagged).findall("detail")), 1)

    def test_tag_goes_inside_detail_once(self):
        for raw in (IngestTests._pli("u1"),
                    b'<event uid="u2"><point lat="1" lon="1"/><detail/></event>',
                    b'<event uid="u3"><point lat="1" lon="1"/></event>'):
            tagged = gw.tag(raw)
            root = ET.fromstring(tagged.split(b"?>", 1)[-1])
            self.assertEqual(len(root.findall("detail")), 1, raw)
            self.assertIsNotNone(root.find("detail/__efdi_relay"), raw)
            self.assertEqual(gw.tag(tagged), tagged)

    def test_dispatch_tags_every_output(self):
        out = _Capture()
        gw.OUTPUTS[:] = [out]
        try:
            gw.dispatch(IngestTests._pli("u4"))
        finally:
            gw.OUTPUTS[:] = []
        self.assertIn(gw.RELAY_TAG, out.sent[0])


class MulticastTests(unittest.TestCase):
    """Real multicast over the loopback interface; skipped where the OS or network forbids it."""

    def test_busy_port_does_not_stop_the_relay(self):
        with mock.patch.object(gw, "open_multicast_listener", side_effect=OSError("address in use")):
            gw.start_multicast_input()  # must not raise
        self.assertGreaterEqual(gw.COUNTERS["gateway_multicast_listen_errors_total"], 1)

    def test_output_reaches_a_group_member(self):
        group, port = "239.255.42.99", _free_port()
        try:
            listener = gw.open_multicast_listener(group, port, "127.0.0.1")
        except OSError as exc:
            self.skipTest(f"multicast not available here: {exc}")
        listener.settimeout(3)
        out = gw.UdpOutput({"host": group, "port": port, "multicast": True, "ttl": 1, "iface": "127.0.0.1"})
        try:
            self.assertEqual(out.name, f"multicast:{group}:{port}")
            out.send(b"<event/>")
            try:
                data, _ = listener.recvfrom(1024)
            except OSError as exc:
                self.skipTest(f"multicast loopback not delivered here: {exc}")
            self.assertEqual(data, b"<event/>")
        finally:
            listener.close()
            out.sock.close()


class ConfigTests(unittest.TestCase):
    def test_udp_targets(self):
        with mock.patch.dict(os.environ, {"TAK_UDP_TARGETS": "a:1, b:2"}, clear=False):
            cfg = gw.load_config()
        udp = [o for o in cfg["outputs"] if o["type"] == "udp"]
        self.assertEqual([(o["host"], o["port"]) for o in udp], [("a", 1), ("b", 2)])

    def test_legacy_single_target(self):
        env = {"TAK_HOST": "h", "TAK_UDP_PORT": "7"}
        with mock.patch.dict(os.environ, env, clear=False):
            os.environ.pop("TAK_UDP_TARGETS", None)
            cfg = gw.load_config()
        self.assertIn({"type": "udp", "host": "h", "port": 7}, cfg["outputs"])

    def test_tak_server_from_env(self):
        with mock.patch.dict(os.environ, {"TAK_SERVER": "tak.example:8089", "TAK_SERVER_VERIFY_HOSTNAME": "0"}):
            cfg = gw.load_config()
        srv = [o for o in cfg["outputs"] if o["type"] == "tcp_client"]
        self.assertEqual(len(srv), 1)
        self.assertEqual((srv[0]["host"], srv[0]["port"], srv[0]["tls"]["verify_hostname"]), ("tak.example", 8089, False))


class HttpTests(unittest.TestCase):
    def setUp(self):
        from http.server import ThreadingHTTPServer
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), gw.Ops)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()

    def test_status_page_and_identity_fields(self):
        import urllib.request
        with urllib.request.urlopen(self.base + "/", timeout=5) as r:
            self.assertIn(b"TAK relay", r.read())
        with urllib.request.urlopen(self.base + "/status", timeout=5) as r:
            st = json.load(r)
        self.assertEqual((st["version"], st["org"], st["system"]), (gw.__version__, gw.gc.ORG, gw.GATEWAY_SYSTEM))
        self.assertEqual(st["ingest_from"], ["local"])


class TcpServerOutputTests(unittest.TestCase):
    def test_stalled_client_does_not_block_others(self):
        port = _free_port()
        out = gw.TcpServerOutput({"port": port})
        stalled = socket.create_connection(("127.0.0.1", port))  # never reads
        stalled.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
        reader = socket.create_connection(("127.0.0.1", port))
        reader.settimeout(5)
        deadline = time.time() + 5
        while out.status()["clients"] < 2 and time.time() < deadline:
            time.sleep(0.05)
        self.assertEqual(out.status()["clients"], 2)

        frame = b"<event/>" + b" " * 1024
        t0 = time.time()
        for _ in range(3000):  # ~3 MB: far more than the stalled peer's buffers hold
            out.send(frame)
        self.assertLess(time.time() - t0, 2.0, "send() blocked on a stalled client")

        got = 0
        while got < 64 * 1024:
            got += len(reader.recv(65536))
        stalled.close()
        reader.close()

    def test_client_cap(self):
        port = _free_port()
        with mock.patch.object(gw, "MAX_TCP_CLIENTS", 2):
            out = gw.TcpServerOutput({"port": port})
            socks = [socket.create_connection(("127.0.0.1", port)) for _ in range(3)]
            deadline = time.time() + 5
            while gw.COUNTERS[f'gateway_output_rejected_total{{output="{out.name}"}}'] < 1 \
                    and time.time() < deadline:
                time.sleep(0.05)
        self.assertEqual(out.status()["clients"], 2)
        self.assertEqual(gw.COUNTERS[f'gateway_output_rejected_total{{output="{out.name}"}}'], 1)
        for s in socks:
            s.close()

    def test_per_address_cap(self):
        port = _free_port()
        with mock.patch.object(gw, "MAX_TCP_CLIENTS", 10), mock.patch.object(gw, "MAX_TCP_CLIENTS_PER_IP", 2):
            out = gw.TcpServerOutput({"port": port})
            socks = [socket.create_connection(("127.0.0.1", port)) for _ in range(3)]
            key = f'gateway_output_rejected_total{{output="{out.name}"}}'
            deadline = time.time() + 5
            while gw.COUNTERS[key] < 1 and time.time() < deadline:
                time.sleep(0.05)
        self.assertEqual(out.status()["clients"], 2)
        self.assertEqual(gw.COUNTERS[key], 1)
        for s in socks:
            s.close()


class TakServerLinkTests(unittest.TestCase):
    def test_one_thread_reads_sends_and_reconnects_after_server_close(self):
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(2)
        srv.settimeout(10)
        pli = gw.bc.make_cot("ANDROID-srv", "a-f-G-U-C", 60.1, 24.9)
        with mock.patch.object(gw, "ingest_event") as ing:
            out = gw.TcpClientOutput({"host": "127.0.0.1", "port": srv.getsockname()[1], "stall_s": 2})
            conn, _ = srv.accept()
            conn.settimeout(5)
            out.send(b"<event/>")
            self.assertEqual(conn.recv(64), b"<event/>")
            conn.sendall(pli)
            deadline = time.time() + 5
            while not ing.called and time.time() < deadline:
                time.sleep(0.05)
            self.assertEqual(ing.call_args.args[2], "server")
            conn.close()                       # the server goes away: the link must notice and reconnect
            again, _ = srv.accept()
            again.close()
        srv.close()


class ConfigValueTests(unittest.TestCase):
    def test_bad_number_is_a_config_error(self):
        errors = []
        with mock.patch.object(gw, "_CONFIG_ERRORS", errors), mock.patch.dict(os.environ, {"X_N": "64 clients"}):
            self.assertEqual(gw._int_env("X_N", 64), 64)
        with mock.patch.object(gw, "_CONFIG_ERRORS", errors), mock.patch.dict(os.environ, {"X_N": "0"}):
            gw._int_env("X_N", 64)
        self.assertEqual(len(errors), 2)

    def test_every_source_has_a_rate_limiter(self):
        self.assertEqual(set(gw._src_limiters), set(gw.bc.ALL_SOURCES))


class DatagramTests(unittest.TestCase):
    def test_datagram_with_two_events_is_dropped(self):
        one = gw.bc.make_cot("u1", "a-f-G", 60, 25)
        self.assertEqual(len(gw._datagram_event(one)), 1)
        self.assertEqual(gw._datagram_event(b"<!-- " + one + b" -->" + one), [])


if __name__ == "__main__":
    unittest.main()
