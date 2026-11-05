#!/usr/bin/env bash
# Removes the automatic start install.sh added (systemd user or system service, crontab line) and
# stops a running relay of this folder. Does not delete this folder.
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
ENV_FILE=$HERE/device.env
cd "$HERE" || exit 1
# shellcheck source=common.sh
. "$HERE/common.sh"
[ ! -f "$ENV_FILE" ] || load_env "$ENV_FILE"

UNIT=efdi-tak-relay-${GATEWAY_SYSTEM:-tak-relay}.service
USER_UNIT=${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/$UNIT
code=0

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

# run.sh restarts the relay 10 s after it exits, so stop the launcher loop first, then the relay.
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

T uninstall_done
exit "$code"
