#!/usr/bin/env bash
# setup-certs.sh -- copy an unpacked EFDI onboarding bundle into ./certs (Linux, macOS).
# The bundle holds <prefix>-cert.pem, <prefix>-key.pem, the CA root (efdi-ca-root.pem) and NOTES.md.
#   demo/setup-certs.sh /path/to/efdi-onboarding-xxxx
set -euo pipefail
bundle=${1:?usage: demo/setup-certs.sh <unpacked onboarding bundle>}
out=$(cd "$(dirname "$0")/.." && pwd)/certs

certs=()
while IFS= read -r -d '' c; do
    [ -f "${c%-cert.pem}-key.pem" ] && certs+=("$c")
done < <(find "$bundle" -maxdepth 1 -name '*-cert.pem' -type f -print0)
[ ${#certs[@]} -eq 1 ] || { echo "Expected exactly one <prefix>-cert.pem + -key.pem pair in $bundle, found ${#certs[@]}" >&2; exit 1; }
ca=$bundle/efdi-ca-root.pem
[ -f "$ca" ] || ca=$(find "$bundle" -maxdepth 1 -type f -name '*.pem' ! -name '*cert*' ! -name '*key*' | head -n 1 || true)
[ -n "$ca" ] || { echo "No CA root (efdi-ca-root.pem) in $bundle" >&2; exit 1; }

mkdir -p "$out"
cp "${certs[0]}" "${certs[0]%-cert.pem}-key.pem" "$out/"
cp "$ca" "$out/efdi-ca-root.pem"
# NOTES.md names the fabric router ("Router endpoint:"); there is no built-in default.
if [ -f "$bundle/NOTES.md" ]; then cp "$bundle/NOTES.md" "$out/"; else echo "WARNING: no NOTES.md in $bundle: set GOAT_ROUTER=tls/<router>:<port>" >&2; fi
# Not readable by other users. The relay container runs as UID 10001 and reads ./certs through
# group 10001 (Docker Desktop on macOS maps the files itself and needs no group).
chmod 750 "$out"
chmod 640 "$out"/*
if [ "$(uname -s)" = Linux ]; then
    sudo chgrp -R 10001 "$out" || echo "WARNING: the relay container cannot read the key: sudo chgrp -R 10001 $out" >&2
fi
echo "==> certs ready in $out"
ls -l "$out"
