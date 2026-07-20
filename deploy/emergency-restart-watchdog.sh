#!/usr/bin/env bash
# Standalone watchdog: listens on MQTT for an emergency-restart request and
# force-restarts the controller service via systemd. Runs as its own service,
# deliberately independent of the controller (no shared Python venv, no dependency on
# led_controller code) so it keeps working even if the controller itself is hung,
# crash-looping, or its venv is broken -- that's the whole point of an "emergency"
# restart path. Its only dependency is mosquitto-clients (`apt-get install
# mosquitto-clients` on Raspberry Pi OS).
#
# Also publishes a retained Home Assistant MQTT Discovery config for a button entity
# on startup, so "Emergency Restart" shows up under the same LED Display Controller
# device without any manual Home Assistant configuration -- same mechanism the
# controller itself uses (see led_controller/mqtt_interface.py), just done here in
# bash since this script must not depend on the controller's own code.
#
# Configure via environment (see led-panel-emergency-restart.service's
# EnvironmentFile) to match your config.yaml's mqtt: block:
#   LED_MQTT_HOST, LED_MQTT_PORT, LED_MQTT_USERNAME, LED_MQTT_PASSWORD
set -euo pipefail

BROKER_HOST="${LED_MQTT_HOST:-localhost}"
BROKER_PORT="${LED_MQTT_PORT:-1883}"
TOPIC="display/control/emergency_restart"
DISCOVERY_TOPIC="homeassistant/button/led_display_controller/emergency_restart/config"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

MQTT_ARGS=(-h "$BROKER_HOST" -p "$BROKER_PORT")
if [[ -n "${LED_MQTT_USERNAME:-}" ]]; then
    MQTT_ARGS+=(-u "$LED_MQTT_USERNAME" -P "${LED_MQTT_PASSWORD:-}")
fi

publish_discovery() {
    mosquitto_pub "${MQTT_ARGS[@]}" -r -t "$DISCOVERY_TOPIC" -m '{
  "unique_id": "led_display_controller_emergency_restart",
  "object_id": "led_display_emergency_restart",
  "name": "Emergency Restart",
  "command_topic": "'"$TOPIC"'",
  "payload_press": "",
  "icon": "mdi:restart-alert",
  "device": {
    "identifiers": ["led_display_controller"],
    "name": "LED Display Controller",
    "manufacturer": "Custom",
    "model": "led-controller"
  }
}'
}

echo "[emergency-restart-watchdog] publishing discovery config to ${BROKER_HOST}:${BROKER_PORT}"
publish_discovery

echo "[emergency-restart-watchdog] watching ${TOPIC} on ${BROKER_HOST}:${BROKER_PORT}"
mosquitto_sub "${MQTT_ARGS[@]}" -t "$TOPIC" | while IFS= read -r _; do
    echo "[emergency-restart-watchdog] restart requested via MQTT"
    "$SCRIPT_DIR/restart-controller.sh"
done
