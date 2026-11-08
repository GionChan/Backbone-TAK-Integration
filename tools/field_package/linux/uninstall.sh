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

remove_autostart
code=$?
stop_relay

T uninstall_done
exit "$code"
