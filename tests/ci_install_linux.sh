#!/usr/bin/env bash
# CI only (ubuntu-latest, passwordless sudo): installs the Linux field package the way a user does.
#   1. English + direct, wheels in the package, --at-boot (systemd system service), with no package
#      index reachable (proves the install needs no network)
#   2. Finnish + local network + device uid, no wheels (venv + pip), default automatic start
#   3. Template package (no certificate, no name): bundle given as a .tar.gz, device name typed in.
#      --template <file.tar.gz> runs only this case, on that exact file (the release artifact).
# Each run: build the package (fake bundle), unpack, install.sh with answers on stdin, check
# device.env, permissions, the printed language, /status and the automatic start, then uninstall
# and check that the service, the processes and the port are gone.
# The fake certificate means the relay cannot reach the fabric; it still serves /status.
set -uo pipefail
REPO=$(cd "$(dirname "$0")/.." && pwd)
# Under $HOME, not /tmp: the folder must be reachable by a systemd service.
ROOT=$(mktemp -d -p "$HOME" field-install-ci.XXXXXX)
SLOT=0123456789abcdef0123456789abcdef
FAILURES=()

check() {
    # check <name> <command...>
    local name=$1
    shift
    if "$@" > /dev/null 2>&1; then echo "PASS $name"; else echo "FAIL $name"; FAILURES+=("$name"); fi
}

status_field() {
    # status_field <field> <wait seconds>: the field of GET :8088/status, exit 1 if no answer.
    python3 - "$1" "$2" << 'EOF'
import json, sys, time, urllib.request
end = time.time() + float(sys.argv[2])
while True:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8088/status", timeout=3) as r:
            print(json.load(r).get(sys.argv[1], ""))
        sys.exit(0)
    except Exception:
        if time.time() > end:
            sys.exit(1)
        time.sleep(2)
EOF
}

not() { ! "$@"; }
running() { pgrep -f "$1/app/tak_gateway.py" > /dev/null; }
mode_of() { [ "$(stat -c %a "$1")" = "$2" ]; }
has_text() { grep -qF "$2" "$1"; }

make_bundle() {
    mkdir -p "$1"
    for f in "$SLOT-cert.pem" "$SLOT-key.pem" efdi-ca-root.pem; do echo "fake" > "$1/$f"; done
    echo "Router endpoint:     tls/router.invalid:7447" > "$1/NOTES.md"
}

install_case() {
    # install_case <name> <system> <package.tar.gz> <answers> <expected texts, |-separated> [install.sh args]
    local name=$1 system=$2 pkg=$3 answers=$4 texts=$5 t
    shift 5
    echo
    echo "=== $name"
    WORK=$ROOT/$name
    mkdir -p "$WORK"
    tar -xzf "$pkg" -C "$WORK"
    PKG=$(find "$WORK" -mindepth 1 -maxdepth 1 -type d | head -n 1)
    printf '%b' "$answers" > "$WORK/answers.txt"
    # shellcheck disable=SC2086  # INSTALL_ENV is "" or one NAME=value word
    (cd "$PKG" && env ${INSTALL_ENV:-} ./install.sh "$@" < "$WORK/answers.txt" > "$WORK/out.txt" 2>&1)
    local code=$?
    cat "$WORK/out.txt"
    check "$name / installer exit code 0 (got $code)" [ "$code" -eq 0 ]
    IFS='|' read -ra want <<< "$texts"
    for t in "${want[@]}"; do check "$name / prints '$t'" has_text "$WORK/out.txt" "$t"; done
    check "$name / device.env GATEWAY_SYSTEM=$system" grep -qx "GATEWAY_SYSTEM=$system" "$PKG/device.env"
    check "$name / device.env is 600" mode_of "$PKG/device.env" 600
    check "$name / key is 600" mode_of "$PKG/certs/$SLOT-key.pem" 600
    check "$name / certs/ is 700" mode_of "$PKG/certs" 700
    check "$name / package folder is 700" mode_of "$PKG" 700
    check "$name / relay answers on :8088" status_field mode 120
    check "$name / /status system" [ "$(status_field system 10)" = "$system" ]
    check "$name / relay process runs" running "$PKG"
}

uninstall_case() {
    local name=$1
    (cd "$PKG" && ./uninstall.sh)
    sleep 3
    check "$name / relay stopped" not running "$PKG"
    check "$name / port 8088 free again" not status_field mode 5
    check "$name / no crontab line left" not has_text <(crontab -l 2> /dev/null) "$PKG/run.sh"
}

template_case() {
    local tpl=$1 bundle=$ROOT/bundle-tpl
    check "template has no certificate or key" not has_text <(tar -tzf "$tpl" | grep -E '\.(pem|key|p12|cbor)$') "."
    make_bundle "$bundle/efdi-onboarding-ci"
    tar -czf "$ROOT/efdi-onboarding-ci.tar.gz" -C "$bundle" efdi-onboarding-ci
    install_case tpl ci-lx-tpl "$tpl" "2\n$ROOT/efdi-onboarding-ci.tar.gz\nci-lx-tpl\n1\n\n\n" \
        "No EFDI certificate bundle found|Certificate copied|Installation complete."
    check "tpl / NOTES.md copied (router)" [ -f "$PKG/certs/NOTES.md" ]
    check "tpl / device.env TAK_MODE=direct" grep -qx "TAK_MODE=direct" "$PKG/device.env"
    uninstall_case tpl
}

finish() {
    echo
    if [ ${#FAILURES[@]} -gt 0 ]; then
        printf 'INSTALL TEST FAILED: %s\n' "${FAILURES[*]}"
        exit 1
    fi
    echo "INSTALL TEST PASSED"
    exit 0
}

if [ "${1:-}" = "--template" ]; then
    INSTALL_ENV="PIP_INDEX_URL=http://127.0.0.1:9/simple"
    template_case "$(cd "$(dirname "$2")" && pwd)/$(basename "$2")"
    finish
fi

make_bundle "$ROOT/bundle"
build() { python3 "$REPO/tools/make_relay_package.py" --platform linux "$@" > /dev/null; }

# 1. English, direct, wheels, --at-boot, no package index. Answers: 2 = English, 1 = direct,
#    Enter = CoT to this machine, Enter = no other devices.
build --system ci-lx-en --cert-dir "$ROOT/bundle" --out "$ROOT/ci-lx-en-tak-relay-linux.tar.gz"
INSTALL_ENV="PIP_INDEX_URL=http://127.0.0.1:9/simple"
install_case en-direct ci-lx-en "$ROOT/ci-lx-en-tak-relay-linux.tar.gz" "2\n1\n\n\n" \
    "Choose language|Installation complete.|Next, on the TAK devices:|CoT goes to 127.0.0.1:6969" --at-boot
UNIT=efdi-tak-relay-ci-lx-en.service
check "en-direct / systemd service active" systemctl is-active --quiet "$UNIT"
check "en-direct / service runs as $(id -un), not root" grep -qx "User=$(id -un)" "/etc/systemd/system/$UNIT"
check "en-direct / dependencies from the package" has_text "$WORK/out.txt" "from the package"
uninstall_case en-direct
check "en-direct / service removed" [ ! -f "/etc/systemd/system/$UNIT" ]
INSTALL_ENV=""

# 2. Finnish, local network, one device uid, no wheels. Answers: 1 = Suomi, 2 = multicast, the uid.
build --system ci-lx-fi --cert-dir "$ROOT/bundle" --out "$ROOT/ci-lx-fi-tak-relay-linux.tar.gz" --no-bundled-wheels
install_case fi-multicast ci-lx-fi "$ROOT/ci-lx-fi-tak-relay-linux.tar.gz" "1\n2\nANDROID-ci\n" \
    "Valitse kieli|Asennus valmis.|Seuraavaksi TAK-laitteisiin:"
check "fi-multicast / device.env TAK_INGEST_UIDS=ANDROID-ci" grep -qx "TAK_INGEST_UIDS=ANDROID-ci" "$PKG/device.env"
check "fi-multicast / /status mode multicast" [ "$(status_field mode 10)" = multicast ]
check "fi-multicast / automatic start registered" has_text "$WORK/out.txt" "Automaattinen käynnistys:"
uninstall_case fi-multicast

# 3. Template.
build --template --out "$ROOT/efdi-tak-relay-ci-linux.tar.gz" --no-bundled-wheels
template_case "$ROOT/efdi-tak-relay-ci-linux.tar.gz"
finish
