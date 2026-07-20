#!/usr/bin/env bash
# Force-restarts the controller service, whether it crashed, hung, or is running fine.
# `systemctl restart` stops it first (SIGTERM, then SIGKILL after TimeoutStopSec if it
# doesn't exit -- this is what actually recovers a genuinely stuck/hung process, unlike
# the service's own Restart=on-failure, which only fires once a process has exited on
# its own) and then starts it fresh.
#
# Safe to run by hand over SSH, from cron, or via emergency-restart-watchdog.sh.
set -euo pipefail

SERVICE_NAME="${LED_PANEL_SERVICE_NAME:-led-panel-controller.service}"

echo "[restart-controller] restarting ${SERVICE_NAME}..."
systemctl restart "$SERVICE_NAME"
echo "[restart-controller] done."
systemctl --no-pager --lines=0 status "$SERVICE_NAME" || true
