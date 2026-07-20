#!/usr/bin/env bash
# This script is intended to be run manually to disable power to the LED panel via the relay.
# It is not intended to be run automatically, and should only be used for testing purposes.
# Like running new display code on a panel bypassing the controller, or testing the panel's power supply and relay wiring.
#
# Usage: ./manual_relay_off.sh [PIN]
#   PIN - BCM GPIO number to drive (default: 21, i.e. physical header pin 40)
#
# Uses raspi-gpio, which ships with Raspberry Pi OS, to set the pin as an output
# and drive it LOW directly. This is a standalone one-shot register write, not a
# running process, so the level is held after the script exits — no Python, no
# venv, and no dependency on anything else in this project.
#
# Note: this assumes an active-high relay (HIGH = energized), so LOW = off. If
# your relay module is active-low, LOW will actually turn it on — in that case
# use manual_relay_on.sh to de-energize it instead.

set -euo pipefail

PIN="${1:-21}"

if ! [[ "$PIN" =~ ^[0-9]+$ ]]; then
    echo "PIN must be a non-negative integer (BCM numbering), got: $PIN" >&2
    exit 1
fi

if ! command -v raspi-gpio >/dev/null 2>&1; then
    echo "raspi-gpio not found. Install it with: sudo apt install raspi-gpio" >&2
    exit 1
fi

raspi-gpio set "$PIN" op dl

echo "GPIO${PIN} set as output, driven LOW."
echo "Relay should now be OFF (if active-high) or ON (if active-low)."
