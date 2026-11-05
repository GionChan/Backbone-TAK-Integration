"""Tests for relay/tak_links.py: TAK-side settings and the TAK Server TLS context (incl. .p12)."""
import datetime
import os
import socket
import ssl
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "relay"))
import tak_links  # noqa: E402

try:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.serialization import pkcs12
    from cryptography.x509.oid import NameOID
except ImportError:
    x509 = None


class EnvTests(unittest.TestCase):
    def test_udp_targets(self):
        with mock.patch.dict(os.environ, {"TAK_UDP_TARGETS": "a:6969, b:4242"}):
            self.assertEqual([(t["host"], t["port"]) for t in tak_links.udp_targets()], [("a", 6969), ("b", 4242)])

    def test_no_tak_server(self):
        with mock.patch.dict(os.environ, {"TAK_SERVER": ""}):
            self.assertIsNone(tak_links.tak_server())

    def test_tak_server_defaults_to_tls_8089(self):
        env = {"TAK_SERVER": "tak.example", "TAK_SERVER_P12": "c.p12", "TAK_SERVER_P12_PASSWORD": "pw"}
        with mock.patch.dict(os.environ, env):
            cfg = tak_links.tak_server()
        self.assertEqual((cfg["host"], cfg["port"]), ("tak.example", 8089))
        self.assertEqual(cfg["tls"]["trust_password"], "pw")  # truststore password defaults to the p12 one
        self.assertTrue(cfg["tls"]["verify_hostname"])

    def test_port_8087_is_plain_tcp(self):
        with mock.patch.dict(os.environ, {"TAK_SERVER": "10.0.0.5:8087"}):
            self.assertNotIn("tls", tak_links.tak_server())


class ModeTests(unittest.TestCase):
    def _outputs(self, **env):
        base = {"TAK_MODE": "", "TAK_SERVER": "", "TAK_LOCAL_OUTPUTS": "", "TAK_UDP_TARGETS": "h:6969"}
        with mock.patch.dict(os.environ, {**base, **env}):
            return [o["type"] + (":mc" if o.get("multicast") else "") for o in tak_links.outputs()]

    def test_direct_is_default(self):
        self.assertEqual(self._outputs(), ["udp", "tcp_server"])

    def test_multicast_replaces_unicast_targets(self):
        self.assertEqual(self._outputs(TAK_MODE="multicast"), ["udp:mc", "tcp_server"])

    def test_server_needs_tak_server(self):
        with self.assertRaisesRegex(tak_links.ConfigError, "TAK_SERVER"):
            self._outputs(TAK_MODE="server")

    def test_server_mode_has_no_local_outputs_by_default(self):
        self.assertEqual(self._outputs(TAK_MODE="server", TAK_SERVER="tak:8087"), ["tcp_client"])
        self.assertEqual(self._outputs(TAK_MODE="server", TAK_SERVER="tak:8087", TAK_LOCAL_OUTPUTS="1"),
                         ["udp", "tcp_server", "tcp_client"])

    def test_unknown_mode_is_an_error(self):
        with mock.patch.dict(os.environ, {"TAK_MODE": "broadcast"}), self.assertRaises(tak_links.ConfigError):
            tak_links.mode()

    def test_bad_values_are_config_errors_not_tracebacks(self):
        for env in ({"TAK_SERVER": "tak.example:abc"}, {"TAK_UDP_TARGETS": "hostonly"},
                    {"TAK_MODE": "multicast", "TAK_MULTICAST_IF": "eth0"},
                    {"TAK_MODE": "multicast", "TAK_MULTICAST_GROUP": "10.0.0.1:6969"},
                    {"TAK_MODE": "multicast", "TAK_MULTICAST_TTL": "0"}):
            with self.subTest(env=env), self.assertRaises(tak_links.ConfigError):
                self._outputs(**env)

    def test_multicast_ingest_defaults_include_lan(self):
        self.assertEqual(tak_links.default_ingest_from("multicast"), "local,lan")
        self.assertEqual(tak_links.default_ingest_from("server"), "local")


def _name(cn):
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])


def _cert(subject_cn, key, issuer_cn, issuer_key, ca=False, san=None):
    now = datetime.datetime.now(datetime.timezone.utc)
    b = (x509.CertificateBuilder().subject_name(_name(subject_cn)).issuer_name(_name(issuer_cn))
         .public_key(key.public_key()).serial_number(x509.random_serial_number())
         .not_valid_before(now - datetime.timedelta(minutes=5)).not_valid_after(now + datetime.timedelta(days=1))
         .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True))
    if san:
        b = b.add_extension(x509.SubjectAlternativeName([x509.DNSName(san)]), critical=False)
    return b.sign(issuer_key, hashes.SHA256())


@unittest.skipIf(x509 is None, "cryptography not installed")
class P12Tests(unittest.TestCase):
    """A local TLS server that requires a client cert, like TAK Server on 8089."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        d = Path(cls.tmp.name)
        ca_key, srv_key, cli_key = (ec.generate_private_key(ec.SECP256R1()) for _ in range(3))
        ca = _cert("Test TAK CA", ca_key, "Test TAK CA", ca_key, ca=True)
        srv = _cert("localhost", srv_key, "Test TAK CA", ca_key, san="localhost")
        cli = _cert("relay-01", cli_key, "Test TAK CA", ca_key)
        pem = serialization.Encoding.PEM
        (d / "ca.pem").write_bytes(ca.public_bytes(pem))
        (d / "srv.pem").write_bytes(srv.public_bytes(pem))
        (d / "srv.key").write_bytes(srv_key.private_bytes(pem, serialization.PrivateFormat.PKCS8,
                                                          serialization.NoEncryption()))
        enc = serialization.BestAvailableEncryption(b"atak")
        (d / "client.p12").write_bytes(pkcs12.serialize_key_and_certificates(b"relay-01", cli_key, cli, None, enc))
        (d / "truststore.p12").write_bytes(pkcs12.serialize_key_and_certificates(b"ca", None, None, [ca], enc))
        cls.d = d

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def _serve_once(self):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(self.d / "srv.pem", self.d / "srv.key")
        ctx.load_verify_locations(self.d / "ca.pem")
        ctx.verify_mode = ssl.CERT_REQUIRED
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        seen = {}

        def run():
            conn, _ = srv.accept()
            try:
                with ctx.wrap_socket(conn, server_side=True) as tls:
                    seen["cn"] = dict(x[0] for x in tls.getpeercert()["subject"])["commonName"]
                    tls.sendall(b"ok")
            except (ssl.SSLError, OSError) as exc:
                seen["error"] = exc
            finally:
                srv.close()

        t = threading.Thread(target=run, daemon=True)
        t.start()
        return srv.getsockname()[1], seen, t

    def test_p12_client_and_truststore(self):
        port, seen, t = self._serve_once()
        tls = {"p12": str(self.d / "client.p12"), "p12_password": "atak",
               "trust_p12": str(self.d / "truststore.p12"), "trust_password": "atak", "verify_hostname": True}
        ctx = tak_links.ssl_context(tls)
        with socket.create_connection(("127.0.0.1", port), timeout=5) as raw, \
                ctx.wrap_socket(raw, server_hostname="localhost") as s:
            self.assertEqual(s.recv(2), b"ok")
        t.join(5)
        self.assertEqual(seen.get("cn"), "relay-01")

    def test_truststore_replaces_public_cas(self):
        ctx = tak_links.ssl_context({"trust_p12": str(self.d / "truststore.p12"), "trust_password": "atak",
                                     "verify_hostname": False})
        # Only the TAK Server CA: with hostname checks off a public CA would accept any certificate.
        self.assertEqual(len(ctx.get_ca_certs()), 1)
        self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED)
        ctx_pem = tak_links.ssl_context({"ca": str(self.d / "ca.pem")})
        self.assertEqual(len(ctx_pem.get_ca_certs()), 1)

    def test_decrypted_key_does_not_stay_on_disk(self):
        made = []
        real = tempfile.mkdtemp

        def spy(**kw):
            made.append(real(**kw))
            return made[-1]

        with mock.patch.object(tak_links.tempfile, "mkdtemp", side_effect=spy):
            tak_links.ssl_context({"p12": str(self.d / "client.p12"), "p12_password": "atak"})
        self.assertEqual(len(made), 1)
        self.assertFalse(os.path.exists(made[0]))

    def test_wrong_password_is_a_clear_error(self):
        with self.assertRaisesRegex(RuntimeError, "wrong password"):
            tak_links.ssl_context({"p12": str(self.d / "client.p12"), "p12_password": "nope"})


if __name__ == "__main__":
    unittest.main()
