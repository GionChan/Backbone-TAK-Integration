#!/usr/bin/env bash
# TAK relay installer (Linux).
#   1. language (fi / en)   2. certificate bundle and device name (template package only)
#   3. mode (direct / local network / TAK Server) and its questions, sharing markers   4. dependencies
#   5. permissions   6. automatic start   7. start now and check /status   8. what to set in TAK
# Choices are saved in device.env; a choice already there is not asked again.
#
# Usage:  ./install.sh                          (asks)
#         ./install.sh --lang en --mode server  (no questions for what is given)
#         ./install.sh --at-boot                (systemd service that starts with the machine;
#                                                runs as you, uses sudo only to install it)
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
ENV_FILE=$HERE/device.env
cd "$HERE"
# shellcheck source=common.sh
. "$HERE/common.sh"

LANG_ARG="" MODE_ARG="" AT_BOOT=0
while [ $# -gt 0 ]; do
    case $1 in
        --lang) LANG_ARG=${2:-}; shift 2 ;;
        --mode) MODE_ARG=${2:-}; shift 2 ;;
        --at-boot) AT_BOOT=1; shift ;;
        *) echo "usage: $0 [--lang fi|en] [--mode direct|multicast|server] [--at-boot]" >&2; exit 2 ;;
    esac
done
case $LANG_ARG in "" | fi | en) ;; *) echo "--lang: fi | en" >&2; exit 2 ;; esac
case $MODE_ARG in "" | direct | multicast | server) ;; *) echo "--mode: direct | multicast | server" >&2; exit 2 ;; esac
[ -f "$ENV_FILE" ] || { T no_env >&2; exit 1; }
load_env "$ENV_FILE"
# The relay, its venv and device.env belong to the user who runs it; root would own them all.
if [ "$(id -u)" -eq 0 ]; then T no_root >&2; exit 1; fi

ask() {
    # ask <prompt> [default] -> REPLY, trimmed. End of input is an empty answer.
    local shown=$1
    [ -z "${2:-}" ] || shown="$1 [$2]"
    printf '%s: ' "$shown"
    IFS= read -r REPLY || REPLY=""
    REPLY=$(printf '%s' "$REPLY" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//; s/^"//; s/"$//')
    [ -n "$REPLY" ] || REPLY=${2:-}
}

stop_after() {
    # Never loop without end: once input ends, every answer is empty.
    [ "$1" -lt 10 ] || { T too_many_tries >&2; exit 1; }
}

choose() {
    # choose <valid answers...> -> REPLY
    local try v
    for ((try = 1; ; try++)); do
        ask "$(T choice)"
        for v in "$@"; do [ "$REPLY" = "$v" ] && return 0; done
        T invalid
        stop_after "$try"
    done
}

ask_file() {
    local try
    for ((try = 1; ; try++)); do
        ask "$1" "${2:-}"
        [ -n "$REPLY" ] && [ -f "$REPLY" ] && return 0
        T srv_missing_file "$REPLY"
        stop_after "$try"
    done
}

B_CERT="" B_KEY="" B_CA="" B_NOTES="" B_TMP=""
find_bundle() {
    # Exactly one <slot>-cert.pem with its -key.pem under $1, plus a CA -> B_CERT, B_KEY, B_CA, B_NOTES.
    local pairs=() c folder
    while IFS= read -r -d '' c; do
        [ -f "${c%-cert.pem}-key.pem" ] && pairs+=("$c")
    done < <(find "$1" -name '*-cert.pem' -type f -print0 2> /dev/null)
    [ ${#pairs[@]} -eq 1 ] || return 1
    B_CERT=${pairs[0]}
    B_KEY=${B_CERT%-cert.pem}-key.pem
    folder=$(dirname "$B_CERT")
    B_CA=$folder/efdi-ca-root.pem
    if [ ! -f "$B_CA" ]; then
        B_CA=$(find "$folder" -maxdepth 1 -type f -name '*.pem' ! -name '*cert*' ! -name '*key*' | head -n 1 || true)
    fi
    [ -n "$B_CA" ] && [ -f "$B_CA" ] || return 1
    B_NOTES=$folder/NOTES.md
}

open_bundle() {
    # A folder, or a .zip / .tar.gz unpacked into a temporary folder (removed after copying).
    if [ -d "$1" ]; then find_bundle "$1"; return; fi
    [ -f "$1" ] || return 1
    B_TMP=$(mktemp -d)
    case $1 in
        *.zip) python3 -m zipfile -e "$1" "$B_TMP" > /dev/null 2>&1 || true ;;
        *.tar.gz | *.tgz) tar -xzf "$1" -C "$B_TMP" 2> /dev/null || true ;;
    esac
    find_bundle "$B_TMP" && return 0
    rm -rf "$B_TMP"
    B_TMP=""
    return 1
}

# ---- 1. language
RELAY_LANG=${LANG_ARG:-${RELAY_LANG:-}}
if [ "$RELAY_LANG" != "fi" ] && [ "$RELAY_LANG" != "en" ]; then
    printf '\nValitse kieli / Choose language\n  1) Suomi\n  2) English\n'
    for ((try = 1; ; try++)); do
        printf 'Valinta / Choice: '
        IFS= read -r a || a=""
        case ${a//[[:space:]]/} in
            1) RELAY_LANG="fi"; break ;;
            2) RELAY_LANG="en"; break ;;
        esac
        [ "$try" -lt 10 ] || { echo "Liian monta virheellistä vastausta / Too many invalid answers." >&2; exit 1; }
    done
fi
set_env RELAY_LANG "$RELAY_LANG"
echo
T title

# ---- 2. certificate bundle and device name (a template package has neither)
CERT_DIR=$HERE/certs
if ! find_bundle "$CERT_DIR"; then
    echo
    T bundle_title
    default=$(find "$HOME/Downloads" -maxdepth 1 -name 'efdi-onboarding*' -printf '%T@ %p\n' 2> /dev/null |
        sort -rn | head -n 1 | cut -d' ' -f2- || true)
    for ((try = 1; ; try++)); do
        ask "$(T bundle_prompt)" "$default"
        [ -n "$REPLY" ] && open_bundle "$REPLY" && break
        T bundle_bad "$REPLY"
        stop_after "$try"
    done
    mkdir -p "$CERT_DIR"
    cp "$B_CERT" "$B_KEY" "$CERT_DIR/"
    cp "$B_CA" "$CERT_DIR/efdi-ca-root.pem"
    if [ -f "$B_NOTES" ]; then cp "$B_NOTES" "$CERT_DIR/"; else T bundle_no_notes; fi
    [ -z "$B_TMP" ] || rm -rf "$B_TMP"
    T bundle_copied "$(basename "$B_CERT")"
fi
if [ -z "${GATEWAY_SYSTEM:-}" ]; then
    echo
    T system_note
    default=$(printf 'tak-relay-%s' "$(hostname)" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9-]/-/g' | cut -c1-63)
    for ((try = 1; ; try++)); do
        ask "$(T system_prompt)" "$default"
        [[ $REPLY =~ ^[a-z0-9][a-z0-9-]{2,62}$ ]] && break
        T system_bad
        stop_after "$try"
    done
    set_env GATEWAY_SYSTEM "$REPLY"
fi

# ---- 3. mode
MODE=${MODE_ARG:-${TAK_MODE:-}}
case $MODE in
    direct | multicast | server) ;;
    *)
        echo
        T mode_title
        T mode_1
        T mode_2
        T mode_3
        choose 1 2 3
        case $REPLY in 1) MODE=direct ;; 2) MODE=multicast ;; *) MODE=server ;; esac
        ;;
esac
set_env TAK_MODE "$MODE"
T mode_set "$(T "mode_$MODE")"

# ---- sharing markers and drawings (off or on; device.env keeps the answer)
if [ "${TAK_SHARE_MARKERS:-}" != 0 ] && [ "${TAK_SHARE_MARKERS:-}" != 1 ]; then
    echo
    T share_title
    T share_1
    T share_2
    choose 1 2
    if [ "$REPLY" = 2 ]; then set_env TAK_SHARE_MARKERS 1; else set_env TAK_SHARE_MARKERS 0; fi
fi
T "share_set_$TAK_SHARE_MARKERS"

# ---- questions for the mode
publishes() { [ "${TAK_INGEST:-0}" = 1 ] || [ "${TAK_SHARE_MARKERS:-0}" = 1 ]; }
if [ "$MODE" = direct ]; then
    # On Linux the TAK apps are usually on other devices: ask where CoT goes, and whose PLI counts.
    if [ -z "${TAK_UDP_TARGETS:-}" ]; then
        for ((try = 1; ; try++)); do
            ask "$(T udp_targets)"
            [ -z "$REPLY" ] && break
            [[ $REPLY =~ ^[^,:[:space:]]+:[0-9]+(,[^,:[:space:]]+:[0-9]+)*$ ]] && { set_env TAK_UDP_TARGETS "$REPLY"; break; }
            T invalid
            stop_after "$try"
        done
    fi
    if publishes && [ -z "${TAK_INGEST_UIDS:-}" ]; then
        ask "$(T direct_uids)"
        [ -z "$REPLY" ] || set_env TAK_INGEST_UIDS "$REPLY"
    fi
fi
if [ "$MODE" = server ]; then
    T srv_hint
    if [ -z "${TAK_SERVER:-}" ]; then
        for ((try = 1; ; try++)); do
            ask "$(T srv_address)"
            [ -n "$REPLY" ] && break
            stop_after "$try"
        done
        set_env TAK_SERVER "$REPLY"
    fi
    trust_guess=$(find certs/tak -maxdepth 1 -name '*.p12' -name '*trust*' 2> /dev/null | head -n 1 || true)
    client_guess=$(find certs/tak -maxdepth 1 -name '*.p12' ! -name '*trust*' 2> /dev/null | head -n 1 || true)
    if [ -z "${TAK_SERVER_P12:-}" ]; then ask_file "$(T srv_p12)" "$client_guess"; set_env TAK_SERVER_P12 "$REPLY"; fi
    if [ -z "${TAK_SERVER_TRUST_P12:-}" ]; then ask_file "$(T srv_trust)" "$trust_guess"; set_env TAK_SERVER_TRUST_P12 "$REPLY"; fi
    if [ -z "${TAK_SERVER_P12_PASSWORD:-}" ]; then
        printf '%s: ' "$(T srv_password)"
        IFS= read -rs pw || pw=""
        echo
        set_env TAK_SERVER_P12_PASSWORD "$pw"
    fi
fi
if [ "$MODE" = multicast ]; then
    T mc_warning
    if publishes && [ -z "${TAK_INGEST_UIDS:-}" ]; then
        ask "$(T mc_uids)"
        [ -z "$REPLY" ] || set_env TAK_INGEST_UIDS "$REPLY"
    fi
fi

# ---- 4. dependencies
bootstrap
T deps_ok

# ---- 5. permissions: the folder holds the org's private key, and device.env may hold a password
chmod 700 "$HERE" "$CERT_DIR"
find "$CERT_DIR" -type d -exec chmod 700 {} +
find "$CERT_DIR" -type f -exec chmod 600 {} +
chmod 600 "$ENV_FILE"
T perms

# ---- 6. automatic start
SYSTEM=${GATEWAY_SYSTEM:-tak-relay}
HTTP_PORT=${GATEWAY_HTTP_PORT:-8088}

unit_text() {
    # unit_text <wanted-by> [user]: the systemd unit. A system unit runs as the installing user,
    # never as root, so nobody who can write this folder gains root through it.
    printf '[Unit]\nDescription=EFDI TAK relay (%s)\nAfter=network-online.target\nWants=network-online.target\n\n' "$SYSTEM"
    printf '[Service]\nType=simple\n'
    [ -z "${2:-}" ] || printf 'User=%s\n' "$2"
    printf 'WorkingDirectory=%s\nExecStart="%s/run.sh"\nRestart=always\nRestartSec=10\n' "$HERE" "$HERE"
    # No PrivateTmp: a package unpacked under /tmp would be invisible to the service.
    printf 'NoNewPrivileges=yes\n\n[Install]\nWantedBy=%s\n' "$1"
}

# A start method of an earlier install is removed first, so only one relay starts for this folder.
remove_autostart > /dev/null || true
METHOD=none
if [ "$AT_BOOT" = 1 ]; then
    T svc_system "$(id -un)"
    tmp=$(mktemp)
    unit_text multi-user.target "$(id -un)" > "$tmp"
    if sudo install -m 644 "$tmp" "/etc/systemd/system/$UNIT" && sudo systemctl daemon-reload &&
        sudo systemctl enable "$UNIT" > /dev/null 2>&1; then
        METHOD=system
    fi
    rm -f "$tmp"
    [ "$METHOD" = system ] || { T svc_failed >&2; exit 1; }
else
    if systemctl --user show-environment > /dev/null 2>&1; then
        T svc_user
        mkdir -p "$(dirname "$USER_UNIT")"
        unit_text default.target > "$USER_UNIT"
        if systemctl --user daemon-reload && systemctl --user enable "$UNIT" > /dev/null 2>&1; then
            METHOD=user
            # Without lingering the user manager, and the relay, start only when the user signs in.
            loginctl enable-linger "$(id -un)" > /dev/null 2>&1 || T linger_hint
        fi
    fi
    if [ "$METHOD" = none ] && command -v crontab > /dev/null 2>&1; then
        T cron_fallback
        if { crontab -l 2> /dev/null | grep -vF "$HERE/run.sh" || true; echo "@reboot cd \"$HERE\" && ./run.sh > /dev/null 2>&1"; } | crontab - 2> /dev/null; then
            METHOD=cron
        fi
    fi
    [ "$METHOD" != none ] || T no_autostart
fi

# ---- 7. start now and check
T starting_now
stop_relay > /dev/null
case $METHOD in
    system) sudo systemctl restart "$UNIT" ;;
    user) systemctl --user restart "$UNIT" ;;
    *) setsid nohup "$HERE/run.sh" > /dev/null 2>&1 < /dev/null & ;;
esac
T waiting
status=$("$VENV_PY" - "$HTTP_PORT" << 'EOF'
import json, sys, time, urllib.request
end = time.time() + 30
while time.time() < end:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{sys.argv[1]}/status", timeout=3) as r:
            d = json.load(r)
        print("ok" if d.get("healthy") else "degraded " + ", ".join(d.get("reasons", [])))
        sys.exit(0)
    except Exception:
        time.sleep(2)
print("none")
EOF
)
case $status in
    ok) T healthy ;;
    degraded*) T not_healthy "${status#degraded }"; T not_healthy_hint ;;
    *) T no_answer "$HTTP_PORT" ;;
esac

# ---- 8. what to set in TAK
echo
T install_done
case $METHOD in
    system) T autostart_system "$UNIT" ;;
    user) T autostart_user "$UNIT" ;;
    cron) T autostart_cron ;;
esac
T restart_note
echo
T next_title
case $MODE in
    direct)
        T next_direct "${TAK_UDP_TARGETS:-${TAK_HOST:-127.0.0.1}:${TAK_UDP_PORT:-6969}}" "${TAK_PORT:-8087}"
        [ "${TAK_INGEST:-0}" != 1 ] || [ -z "${TAK_UDP_IN_PORT:-}" ] || T next_direct_pli "$TAK_UDP_IN_PORT"
        T firewall_hint "${TAK_PORT:-8087}" "${TAK_UDP_IN_PORT:-6971}"
        ;;
    multicast)
        group=${TAK_MULTICAST_GROUP:-239.2.3.1:6969}
        T next_multicast "$group"
        T firewall_hint "${TAK_PORT:-8087}" "${group##*:}"
        ;;
    server) T next_server ;;
esac
echo
T status_page "http://127.0.0.1:$HTTP_PORT/"
T doctor_hint
T uninstall_hint
exit 0
