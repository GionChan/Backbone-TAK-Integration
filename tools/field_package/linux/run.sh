#!/usr/bin/env bash
# TAK relay launcher (Linux): runs the relay in the foreground and restarts it if it stops.
# Normally started by the systemd service or the crontab line that install.sh adds.
# Usage:  ./run.sh               (reads device.env next to this script)
#         ./run.sh --check-only  (preflight with app/doctor.py; does not start the relay)
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
ENV_FILE=$HERE/device.env
cd "$HERE" || exit 1
# shellcheck source=common.sh
. "$HERE/common.sh"

[ -f "$ENV_FILE" ] || { T no_env >&2; exit 1; }
load_env "$ENV_FILE"
bootstrap

if [ "${1:-}" = "--check-only" ]; then
    exec "$VENV_PY" "$HERE/app/doctor.py"
fi

mkdir -p "$HERE/logs"
log_lines() {
    # Each line into the log of its own day (a relay that runs for weeks does not keep writing the
    # first day's file); on a terminal also to the screen. Logs older than 14 days are deleted.
    local line day
    while IFS= read -r line; do
        printf -v day '%(%Y%m%d)T' -1
        printf '%s\n' "$line" >> "$HERE/logs/relay-$day.log"
        [ ! -t 1 ] || printf '%s\n' "$line"
    done
}
while true; do
    find "$HERE/logs" -name 'relay-*.log' -mtime +14 -delete 2> /dev/null || true
    T starting "$(date +%H:%M:%S)" "$HERE/logs/relay-$(date +%Y%m%d).log"
    "$VENV_PY" -u "$HERE/app/tak_gateway.py" 2>&1 | log_lines
    T stopped "$(date +%H:%M:%S)" "${PIPESTATUS[0]}"
    sleep 10
done
