"""Zenoh session config for the EFDI goat fabric (mTLS) with a local-router fallback.

Public API: make_config(), ORG, KEY_PREFIX, ROUTER, LOCAL_ROUTER.

Identity (see identity.py): GOAT_CERT/GOAT_KEY/GOAT_CA, else one bundle in GOAT_CERT_DIR,
<repo>/certs, ./certs or /certs. ORG = GOAT_ORG, else the cert CN.

Endpoints:
  GOAT_ROUTER        mTLS fabric router. Default: the "Router endpoint" in the bundle's NOTES.md.
                     With a certificate but neither of these the process exits.
  GOAT_LOCAL_ROUTER  plain-TCP router used when no bundle is found (default tcp/localhost:7447).
                     For backward compatibility a tcp/ value in GOAT_ROUTER is used here too.
"""
import json
import os

import zenoh

import identity


_CERT, _KEY, _CA = identity.resolve_bundle()
_env_router = os.environ.get("GOAT_ROUTER", "")
ROUTER = identity.router_for(_CERT)
LOCAL_ROUTER = os.environ.get("GOAT_LOCAL_ROUTER") or (
    _env_router if _env_router.startswith("tcp/") else "tcp/localhost:7447")

# Without a bundle there is no slot: "local" keeps the local demo namespace separate.
ORG = identity.org_for(_CERT) or "local"
KEY_PREFIX = f"{ORG}/sensor/v1"
if _CERT and ORG == "local":
    # Writes outside your slot are silently dropped by the fabric, so fail loudly here instead.
    raise SystemExit(f"cannot determine the org slot from {_CERT}: set GOAT_ORG=<your slot id>")
if _CERT and not ROUTER:
    raise SystemExit(f"no fabric router: {os.path.dirname(_CERT)} has no NOTES.md with a 'Router endpoint:' "
                     "line; set GOAT_ROUTER=tls/<router>:<port> from your onboarding bundle")


def make_config():
    """Return (zenoh.Config, is_real_fabric: bool)."""
    conf = zenoh.Config()
    conf.insert_json5("mode", '"client"')
    # Loading the client cert plus the OS cert store can exceed the default 10 s open timeout
    # on slow Windows hosts before a TCP attempt is even made; raw TLS completes in < 1 s.
    conf.insert_json5("transport/unicast/open_timeout", "60000")
    # Relayed mesh paths stall for > 1 s at times; the default 10 s lease then drops the session.
    conf.insert_json5("transport/link/tx/lease", os.environ.get("GOAT_LEASE_MS", "60000"))

    if _CERT and _KEY and _CA:
        conf.insert_json5("connect/endpoints", json.dumps([ROUTER]))
        # All TLS keys in ONE call: set one by one, the client cert can silently go unsent.
        conf.insert_json5("transport/link/tls", json.dumps({
            "root_ca_certificate": _CA,
            "connect_certificate": _CERT,
            "connect_private_key": _KEY,
            "enable_mtls": True,
            "verify_name_on_connect": True,
        }))
        return conf, True

    conf.insert_json5("connect/endpoints", json.dumps([LOCAL_ROUTER]))
    return conf, False
