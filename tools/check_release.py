#!/usr/bin/env python3
"""Release consistency check, used by .github/workflows/release.yml.

    python tools/check_release.py                      # branch dry run: versions agree?
    python tools/check_release.py --tag v1.1.0 --notes notes.md

Checks that relay/tak_gateway.py __version__, the newest CHANGELOG.md section and the image tag
in docker-compose.yml agree, and with --tag that the tag is v<that version>. --notes writes
that CHANGELOG section (the release notes). Exit code 1 on any mismatch. Stdlib only.
"""
import argparse
import os
import re
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


def _read(rel: str) -> str:
    with open(os.path.join(REPO_ROOT, rel), encoding="utf-8") as f:
        return f.read()


def relay_version() -> str:
    m = re.search(r'^__version__ = "([^"]+)"', _read("relay/tak_gateway.py"), re.MULTILINE)
    return m.group(1) if m else ""


def changelog_section(text: str) -> tuple:
    """(version, body) of the newest '## X.Y.Z' section."""
    m = re.search(r"^## (\d+\.\d+\.\d+)\b[^\n]*\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    return (m.group(1), m.group(2).strip()) if m else ("", "")


def compose_image_tag() -> str:
    m = re.search(r"image: efdi-tak-relay:(\S+)", _read("docker-compose.yml"))
    return m.group(1) if m else ""


def check(tag: str = None) -> list:
    """List of problems; empty when everything agrees."""
    problems = []
    version = relay_version()
    if not _VERSION_RE.match(version):
        problems.append(f"relay/tak_gateway.py __version__ {version!r} is not X.Y.Z")
    log_version, body = changelog_section(_read("CHANGELOG.md"))
    if log_version != version:
        problems.append(f"newest CHANGELOG.md section is {log_version!r}, relay is {version!r}")
    if not body:
        problems.append("newest CHANGELOG.md section is empty")
    if compose_image_tag() != version:
        problems.append(f"docker-compose.yml image tag is {compose_image_tag()!r}, relay is {version!r}")
    if tag is not None and tag != f"v{version}":
        problems.append(f"tag {tag!r} does not match relay version v{version}")
    return problems


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--tag", help="the git tag being released, e.g. v1.1.0")
    p.add_argument("--notes", help="write the release notes (newest CHANGELOG section) to this file")
    args = p.parse_args()
    problems = check(args.tag)
    for problem in problems:
        print(f"ERROR: {problem}")
    if problems:
        return 1
    version = relay_version()
    if args.notes:
        _, body = changelog_section(_read("CHANGELOG.md"))
        with open(args.notes, "w", encoding="utf-8") as f:
            f.write(body + "\n")
    print(f"release {version}: versions agree" + (f", tag {args.tag}" if args.tag else ""))
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
            f.write(f"version={version}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
