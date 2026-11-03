#!/usr/bin/env python3
"""Register this repo's topics in the EFDI portal.

WRITES TO THE SHARED PORTAL (visible to other vendors and validators) - run it yourself:

    python -m pip install cbor2 requests
    python tools/register_portal_topics.py            # dry run: prints what it would send
    python tools/register_portal_topics.py --check    # read-only: test the token
    python tools/register_portal_topics.py --apply    # really registers

    # One new field device's heartbeat topic only (before shipping a
    # tools/make_relay_package.py --system <name> package, see docs/en/field-package.md):
    python tools/register_portal_topics.py --add-system field-relay-01 --apply

The portal token is read from your own bundle (<org>-goat-cli.cbor, goat_cli_extras.portal_token)
and is never printed. Bundle search: GOAT_BUNDLE_DIR (os.pathsep-separated), ./certs,
~/Downloads/efdi-onboarding-*. Org slot: GOAT_ORG, else the bundle file prefix.
Re-running is safe: an existing topic is reported (HTTP 409 or similar) and skipped.

Notes
  * key_pattern is matched by the portal as a literal string. The fan-out topics end in "**"
    because the real keys end in a per-object uid; whether the portal accepts a wildcard is not
    confirmed by the onboarding doc. If one is rejected, the others are unaffected.
  * SYSTEMS must match the systems registered in the portal Workbench, or the heartbeats are
    not attributed to them.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

import cbor2
import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
SYSTEMS = ["tak-gateway", "edge-ai"]


def topics_for(org: str) -> list:
    return [
        {"key_pattern": f"{org}/{s}/heartbeat/v1", "format": "json",
         "description": f"Mandatory liveness heartbeat of system {s} (60 s)"} for s in SYSTEMS
    ] + [
        {"key_pattern": f"{org}/tak/cot/v1/**", "format": "text",
         "description": "CoT 2.0 XML markers for TAK (one per object, uid-suffixed key)"},
        {"key_pattern": f"{org}/tak/pli/v1/**", "format": "text",
         "description": "Friendly position reports (CoT a-f-*) from our TAK clients, published by tak-gateway"},
        {"key_pattern": f"{org}/exercise/**", "format": "json",
         "description": "SIMULATED exercise injects (demo scenarios). Not real reports: every body has "
                        "exercise=true, classification=SIMULATED"},
    ]


def newest_valid_profile():
    """(org, profile) of the most recently issued, unexpired goat-cli bundle found."""
    dirs = [Path(d) for d in os.environ.get("GOAT_BUNDLE_DIR", "").split(os.pathsep) if d]
    dirs += [REPO_ROOT / "certs"]
    dirs += sorted((Path.home() / "Downloads").glob("efdi-onboarding-*"))
    want = os.environ.get("GOAT_ORG", "").strip()
    best = None
    for d in dirs:
        for f in sorted(d.glob("*-goat-cli.cbor")) if d.is_dir() else []:
            org = f.name[: -len("-goat-cli.cbor")]
            if want and org != want:
                continue
            data = cbor2.loads(f.read_bytes())
            exp = data.get("expires_at", 0)
            print(f"profile {f}  issued={time.strftime('%Y-%m-%d', time.gmtime(data.get('issued_at', 0)))} "
                  f"expires={time.strftime('%Y-%m-%d', time.gmtime(exp))}{'  EXPIRED' if exp < time.time() else ''}")
            if exp >= time.time() and (best is None or data["issued_at"] > best[2]["issued_at"]):
                best = (f, org, data)
    if best is None:
        sys.exit("no valid (unexpired) <org>-goat-cli.cbor found - set GOAT_BUNDLE_DIR or get a fresh bundle")
    print(f"using: {best[0]}")
    return best[1], best[2]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="actually send (default: dry run)")
    ap.add_argument("--check", action="store_true", help="read-only: list existing topics to test the token")
    ap.add_argument("--add-system", metavar="NAME", help="register only this one field device's heartbeat "
                     "topic (<org>/NAME/heartbeat/v1) instead of the full list -- use this for "
                     "a new tools/make_relay_package.py --system NAME device")
    args = ap.parse_args()

    org, data = newest_valid_profile()
    extras = data["goat_cli_extras"]
    token = extras["portal_token"]
    token = token.decode() if isinstance(token, bytes) else token
    portal = extras["portal_endpoint"]
    portal = portal.decode() if isinstance(portal, bytes) else portal
    print(f"portal: {portal}   vendor: {org}   mode: {'APPLY' if args.apply else 'dry run'}")

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    if args.check:
        r = requests.get(f"{portal}/api/vendors/{org}/topics", headers=headers, timeout=20)
        print("token check (GET topics):", r.status_code, r.text[:400])
        return 0 if r.ok else 1

    if args.add_system:
        topics = [{"key_pattern": f"{org}/{args.add_system}/heartbeat/v1", "format": "json",
                   "description": f"Mandatory liveness heartbeat of system {args.add_system} (60 s)"}]
    else:
        topics = topics_for(org)

    for t in topics:
        if not args.apply:
            print("would register:", json.dumps(t))
            continue
        r = requests.post(f"{portal}/api/vendors/{org}/topics", headers=headers, data=json.dumps(t), timeout=20)
        print(f"{r.status_code}  {t['key_pattern']}  {r.text[:160]}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
