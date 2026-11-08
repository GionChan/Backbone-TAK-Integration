# Shared helpers of the Linux field package. Sourced by install.sh, run.sh and uninstall.sh,
# which set HERE (the package folder) and ENV_FILE (its device.env) first.
# shellcheck shell=bash

# Dependencies, the same pins as tools/make_relay_package.FIELD_REQUIREMENTS.
ZENOH_REQ="eclipse-zenoh==1.9.0"
CRYPTOGRAPHY_REQ="cryptography==46.0.3"

T() {
    # T <key> [values...]: the message in $RELAY_LANG (default en) from lang.txt, %s = the values.
    local key=$1 fmt
    shift
    fmt=$(awk -F'|' -v l="${RELAY_LANG:-en}" -v k="$key" \
        '$1 == l && $2 == k { sub(/^[^|]*\|[^|]*\|/, ""); print; exit }' "$HERE/lang.txt")
    [ -n "$fmt" ] || fmt=$key
    # shellcheck disable=SC2059  # the format is our own text from lang.txt, never input
    printf -- "$fmt\n" "$@"
}

load_env() {
    # Exports every KEY=value line of device.env (comments and empty values skipped). The file is
    # parsed, never sourced: a value is data, not shell code.
    local line
    while IFS= read -r line || [ -n "$line" ]; do
        line=${line%$'\r'}
        if [[ $line =~ ^[[:space:]]*([A-Za-z_][A-Za-z0-9_]*)[[:space:]]*=[[:space:]]*(.*[^[:space:]])[[:space:]]*$ ]]; then
            export "${BASH_REMATCH[1]}=${BASH_REMATCH[2]}"
        fi
    done < "$1"
}

set_env() {
    # set_env KEY VALUE: replaces "KEY=..." or "# KEY=..." in device.env, else appends; exports it.
    local tmp
    tmp=$(mktemp "$ENV_FILE.XXXXXX")
    K=$1 V=$2 awk '
        !done && $0 ~ ("^[[:space:]]*#?[[:space:]]*" ENVIRON["K"] "[[:space:]]*=") {
            print ENVIRON["K"] "=" ENVIRON["V"]; done = 1; next }
        { print }
        END { if (!done) print ENVIRON["K"] "=" ENVIRON["V"] }' "$ENV_FILE" > "$tmp"
    chmod 600 "$tmp"
    mv "$tmp" "$ENV_FILE"
    export "$1=$2"
}

bootstrap() {
    # Sets VENV_PY: .venv with the dependencies, created once. Packages built with wheels (the
    # default) install from wheels/<arch>/ without network.
    local py=${PYTHON:-python3} venv=$HERE/.venv wheels marker p
    wheels=$HERE/wheels/$(uname -m)
    if ! command -v "$py" > /dev/null 2>&1 || ! "$py" -c 'import sys; sys.exit(sys.version_info < (3, 10))'; then
        T no_python >&2
        exit 1
    fi
    if [ ! -x "$venv/bin/python" ]; then
        T venv
        if ! "$py" -m venv "$venv" > /dev/null 2>&1; then
            rm -rf "$venv"
            T no_venv >&2
            exit 1
        fi
    fi
    VENV_PY=$venv/bin/python
    local wanted=("$ZENOH_REQ") missing=()
    # cryptography reads the TAK Server .p12 files; from the network only when they are used.
    if [ -d "$wheels" ] || [ "${TAK_MODE:-}" = server ] || [ -n "${TAK_SERVER_P12:-}${TAK_SERVER_TRUST_P12:-}" ]; then
        wanted+=("$CRYPTOGRAPHY_REQ")
    fi
    marker=$venv/deps-installed.txt
    for p in "${wanted[@]}"; do
        grep -qxF "$p" "$marker" 2> /dev/null || missing+=("$p")
    done
    [ ${#missing[@]} -gt 0 ] || return 0
    if [ -d "$wheels" ]; then
        T deps_offline
        # A Python the bundled wheels do not cover (e.g. a newer version) falls back to the network.
        if ! "$VENV_PY" -m pip install --quiet --no-index --find-links "$wheels" "${missing[@]}" 2> /dev/null; then
            T deps "${missing[*]}"
            "$VENV_PY" -m pip install --quiet --find-links "$wheels" "${missing[@]}" || { T pip_failed >&2; exit 1; }
        fi
    else
        T deps "${missing[*]}"
        "$VENV_PY" -m pip install --quiet "${missing[@]}" || { T pip_failed >&2; exit 1; }
    fi
    printf '%s\n' "${missing[@]}" >> "$marker"
}

unit_names() {
    # UNIT and USER_UNIT of this folder's relay, from GATEWAY_SYSTEM: call after device.env is loaded.
    UNIT=efdi-tak-relay-${GATEWAY_SYSTEM:-tak-relay}.service
    USER_UNIT=${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/$UNIT
}

remove_autostart() {
    # Removes every start method an install may have added: systemd user unit, system unit, crontab.
    # Returns 1 when the system unit could not be removed (no sudo).
    local code=0
    unit_names
    if [ -f "$USER_UNIT" ]; then
        systemctl --user disable --now "$UNIT" > /dev/null 2>&1 || true
        rm -f "$USER_UNIT"
        systemctl --user daemon-reload > /dev/null 2>&1 || true
        T svc_removed "$UNIT"
    fi
    if [ -f "/etc/systemd/system/$UNIT" ]; then
        if sudo systemctl disable --now "$UNIT" > /dev/null 2>&1 && sudo rm -f "/etc/systemd/system/$UNIT" &&
            sudo systemctl daemon-reload; then
            T svc_removed "$UNIT"
        else
            T svc_system_sudo "$UNIT" >&2
            code=1
        fi
    fi
    if crontab -l 2> /dev/null | grep -qF "$HERE/run.sh"; then
        crontab -l 2> /dev/null | grep -vF "$HERE/run.sh" | crontab -
        T cron_removed
    fi
    return "$code"
}

stop_relay() {
    # run.sh restarts the relay 10 s after it exits, so stop the launcher loop first, then the relay.
    local pattern pid args
    for pattern in "$HERE/run.sh" "$HERE/app/tak_gateway.py"; do
        while read -r pid args; do
            case $args in
                *"$pattern"*)
                    T stopping "$pid"
                    kill "$pid" 2> /dev/null || true
                    ;;
            esac
        done < <(ps -eo pid=,args=)
    done
}
