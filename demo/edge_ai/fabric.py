"""mTLS connection to the EFDI Zenoh backbone for the edge-AI node.

Uses relay/identity.py (copied next to this file in the Docker image) for the bundle and the
org slot, so every component finds certificates the same way. Same rule as the relay: all TLS
settings go in ONE transport/link/tls JSON blob or the client cert is silently not presented.

Env:
  GOAT_CERT / GOAT_KEY / GOAT_CA   explicit PEM paths  (else GOAT_CERT_DIR, ./certs, /certs)
  GOAT_ORG (or EDGE_ORG)           org slot (default: the cert CN)
  GOAT_ROUTER                      mTLS router (default the EFDI router below)
  GOAT_LOCAL_ROUTER                plain-TCP router when no bundle is found
"""
from __future__ import annotations

import json
import os
import sys

import zenoh

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "relay"))
import identity  # noqa: E402

if os.environ.get("EDGE_ORG") and not os.environ.get("GOAT_ORG"):
    os.environ["GOAT_ORG"] = os.environ["EDGE_ORG"]

_CERT, _KEY, _CA = identity.resolve_bundle()
ORG = identity.org_for(_CERT) or "local"
_r = os.environ.get("GOAT_ROUTER", "")
ROUTER = _r if _r.startswith("tls/") else "tls/router.example:7447"
LOCAL_ROUTER = os.environ.get("GOAT_LOCAL_ROUTER") or (_r if _r.startswith("tcp/") else "tcp/localhost:7447")


def open_session():
    """Return (zenoh.Session, bool is_real_fabric)."""
    cert, key, ca = _CERT, _KEY, _CA
    conf = zenoh.Config()
    conf.insert_json5("mode", '"client"')
    conf.insert_json5("transport/unicast/open_timeout", "60000")
    conf.insert_json5("transport/link/tx/lease", os.environ.get("GOAT_LEASE_MS", "60000"))
    if cert and key and ca:
        conf.insert_json5("connect/endpoints", json.dumps([ROUTER]))
        conf.insert_json5("transport/link/tls", json.dumps({
            "root_ca_certificate": ca,
            "connect_certificate": cert,
            "connect_private_key": key,
            "enable_mtls": True,
            "verify_name_on_connect": True,
        }))
        return zenoh.open(conf), True
    conf.insert_json5("connect/endpoints", json.dumps([LOCAL_ROUTER]))
    return zenoh.open(conf), False
