#!/usr/bin/env bash
# This script is intended to be run manually to enable power to the LED panel via the relay.
# It is not intended to be run automatically, and should only be used for testing purposes.
# Like running new display code on a panel bypassing the controller, or testing the panel's power supply and relay wiring.
#
# Usage: ./manual_relay_on.sh [PIN]
#   PIN - BCM GPIO number to drive (default: 21, i.e. physical header pin 40)
#
# Uses pinctrl (or raspi-gpio as a fallback on older Raspberry Pi OS versions) to
# set the pin as an output and drive it HIGH directly. This is a standalone
# one-shot register write, not a running process, so the level is held after the
# script exits — no Python, no venv, and no dependency on anything else in this
# project.
#
# Note: this assumes an active-high relay (HIGH = energized). If your relay
# module is active-low, HIGH will actually turn it off — in that case use
# manual_relay_off.sh to energize it instead.

set -euo pipefail

PIN="${1:-21}"

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

"$GPIO_TOOL" set "$PIN" op dh

echo "GPIO${PIN} set as output, driven HIGH (via $GPIO_TOOL)."
echo "Relay should now be ON (if active-high) or OFF (if active-low)."
echo
echo "Readback:"
"$GPIO_TOOL" get "$PIN"
