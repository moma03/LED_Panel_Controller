#!/usr/bin/env bash
# This script is intended to be run manually to disable power to the LED panel via the relay.
# It is not intended to be run automatically, and should only be used for testing purposes.
# Like running new display code on a panel bypassing the controller, or testing the panel's power supply and relay wiring.
#
# Usage: ./manual_relay_off.sh [PIN]
#   PIN - BCM GPIO number to drive (default: 0, i.e. physical header pin 27)
#
# Uses pinctrl (or raspi-gpio as a fallback on older Raspberry Pi OS versions) to
# set the pin as an output and drive it LOW directly. This is a standalone
# one-shot register write, not a running process, so the level is held after the
# script exits — no Python, no venv, and no dependency on anything else in this
# project.
#
# Note: this assumes an active-high relay (HIGH = energized), so LOW = off. If
# your relay module is active-low, LOW will actually turn it on — in that case
# use manual_relay_on.sh to de-energize it instead.

set -euo pipefail

PIN="${1:-0}"

if ! [[ "$PIN" =~ ^[0-9]+$ ]]; then
    echo "PIN must be a non-negative integer (BCM numbering), got: $PIN" >&2
    exit 1
fi

if command -v pinctrl >/dev/null 2>&1; then
    GPIO_TOOL=pinctrl
elif command -v raspi-gpio >/dev/null 2>&1; then
    GPIO_TOOL=raspi-gpio
else
    echo "Neither pinctrl nor raspi-gpio found. Install with: sudo apt install raspi-gpio" >&2
    exit 1
fi

"$GPIO_TOOL" set "$PIN" op dl

echo "GPIO${PIN} set as output, driven LOW (via $GPIO_TOOL)."
echo "Relay should now be OFF (if active-high) or ON (if active-low)."
echo
echo "Readback:"
"$GPIO_TOOL" get "$PIN"
