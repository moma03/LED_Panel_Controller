"""MQTT I/O adapter — the only module that knows about MQTT topics/payloads.

Incoming messages are decoded into (Command, payload) tuples and handed off
through a thread-safe queue; the controller's single-threaded loop is the
only place that acts on them. This module never touches state or process
logic itself, keeping the transport swappable per the design goals.

Accepts any object that duck-types paho.mqtt.client.Client (on_connect,
on_message, connect, loop_start, loop_stop, subscribe, publish), so tests can
inject a fake client without a real broker.
"""

from __future__ import annotations

import json
import queue
import sys
from typing import Protocol

from .commands import Command
from .commands import State as ControllerState
from .config import AppConfig

TOPIC_PROGRAMS = "display/programs"
TOPIC_STATUS = "display/status"
TOPIC_CURRENT = "display/current"
TOPIC_ERRORS = "display/errors"

TOPIC_PENDING_PROGRAM = "display/pending/program"
TOPIC_PENDING_SUBPROGRAM = "display/pending/subprogram"

# Home Assistant MQTT Discovery: https://www.home-assistant.io/integrations/mqtt/#discovery-messages
_DISCOVERY_PREFIX = "homeassistant"
_NODE_ID = "led_display_controller"
_DEVICE = {
    "identifiers": [_NODE_ID],
    "name": "LED Display Controller",
    "manufacturer": "Custom",
    "model": "led-controller",
}
# Reads the pending program/subprogram selects (see _select_config below) so a single
# button press can carry both fields without a dedicated MQTT round-trip per field.
_START_SWITCH_COMMAND_TEMPLATE = (
    "{% set sub = states('select.led_display_subprogram') %}"
    "{{ {'program': states('select.led_display_program'),"
    " 'subprogram': none if sub in ['none', 'unknown', 'unavailable'] else sub} | tojson }}"
)

_CONTROL_TOPIC_COMMANDS = {
    "display/control/power_on": Command.POWER_ON,
    "display/control/start": Command.START,
    "display/control/switch": Command.SWITCH,
    "display/control/stop": Command.STOP,
    "display/control/retry": Command.RETRY,
    "display/control/shutdown": Command.SHUTDOWN,
}


class MQTTClient(Protocol):
    on_connect: object
    on_message: object

    def connect(self, host: str, port: int) -> None: ...
    def loop_start(self) -> None: ...
    def loop_stop(self) -> None: ...
    def subscribe(self, topic: str) -> None: ...
    def publish(self, topic: str, payload: str, retain: bool = False) -> None: ...


class MQTTInterface:
    def __init__(self, client: MQTTClient, command_queue: "queue.Queue[tuple[Command, dict]]"):
        self._client = client
        self._queue = command_queue
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message

    # -- lifecycle ---------------------------------------------------------

    def start(self, host: str, port: int) -> None:
        self._client.connect(host, port)
        self._client.loop_start()

    def stop(self) -> None:
        self._client.loop_stop()

    def _on_connect(self, _client, _userdata, _connect_flags, reason_code, _properties=None) -> None:
        if reason_code != 0:
            print(f"MQTT connection failed: {reason_code}", file=sys.stderr)
            return
        for topic in _CONTROL_TOPIC_COMMANDS:
            self._client.subscribe(topic)

    def _on_message(self, _client, _userdata, message) -> None:
        print(f"[led-controller] MQTT message received: {message.topic} {message.payload}")
        command = _CONTROL_TOPIC_COMMANDS.get(message.topic)
        if command is None:
            return
        raw_payload = message.payload
        if isinstance(raw_payload, bytes):
            raw_payload = raw_payload.decode("utf-8")
        try:
            payload = json.loads(raw_payload) if raw_payload else {}
        except json.JSONDecodeError:
            payload = {}
        self._queue.put((command, payload))

    # -- publishing ---------------------------------------------------------

    def publish_programs(self, config: AppConfig) -> None:
        data = [
            {
                "id": program.id,
                "name": program.name,
                "subprograms": [
                    {"id": sub.id, "name": sub.name} for sub in program.subprograms.values()
                ],
            }
            for program in config.programs.values()
        ]
        self._client.publish(TOPIC_PROGRAMS, json.dumps(data), retain=True)

    def publish_status(self, state: ControllerState) -> None:
        self._client.publish(TOPIC_STATUS, json.dumps({"state": state.value}), retain=True)

    def publish_current(self, program_id: str | None, subprogram_id: str | None) -> None:
        payload = {"program": program_id, "subprogram": subprogram_id}
        self._client.publish(TOPIC_CURRENT, json.dumps(payload), retain=True)

    def publish_error(self, message: str) -> None:
        print(f"[led-controller] {message}", file=sys.stderr)
        self._client.publish(TOPIC_ERRORS, json.dumps({"message": message}))

    def publish_discovery(self, config: AppConfig) -> None:
        """Publishes retained Home Assistant MQTT Discovery configs so entities are
        created/updated automatically from config.yaml — no hand-maintained option
        lists on the Home Assistant side, per the single-source-of-truth design goal."""
        for object_id, entity_config in self._sensor_configs():
            self._publish_discovery_entity("sensor", object_id, entity_config)
        for object_id, entity_config in self._select_configs(config):
            self._publish_discovery_entity("select", object_id, entity_config)
        for object_id, entity_config in self._button_configs():
            self._publish_discovery_entity("button", object_id, entity_config)

    def _publish_discovery_entity(self, component: str, object_id: str, entity_config: dict) -> None:
        topic = f"{_DISCOVERY_PREFIX}/{component}/{_NODE_ID}/{object_id}/config"
        payload = {
            "unique_id": f"{_NODE_ID}_{object_id}",
            "device": _DEVICE,
            **entity_config,
        }
        self._client.publish(topic, json.dumps(payload), retain=True)

    def _sensor_configs(self):
        return [
            ("status", {
                "name": "Status",
                "state_topic": TOPIC_STATUS,
                "value_template": "{{ value_json.state }}",
                "icon": "mdi:state-machine",
            }),
            ("current_program", {
                "name": "Current Program",
                "state_topic": TOPIC_CURRENT,
                "value_template": "{{ value_json.program | default('none') }}",
                "icon": "mdi:monitor-dashboard",
            }),
            ("current_subprogram", {
                "name": "Current Subprogram",
                "state_topic": TOPIC_CURRENT,
                "value_template": "{{ value_json.subprogram | default('none') }}",
                "icon": "mdi:subdirectory-arrow-right",
            }),
            ("last_error", {
                "name": "Last Error",
                "state_topic": TOPIC_ERRORS,
                "value_template": "{{ value_json.message }}",
                "icon": "mdi:alert-circle-outline",
            }),
        ]

    def _select_configs(self, config: AppConfig):
        subprogram_ids = sorted(
            {sub_id for program in config.programs.values() for sub_id in program.subprograms}
        )
        return [
            ("program", {
                "name": "Program",
                "options": list(config.programs.keys()),
                "command_topic": TOPIC_PENDING_PROGRAM,
                "state_topic": TOPIC_PENDING_PROGRAM,
                "retain": True,
                "icon": "mdi:monitor",
            }),
            ("subprogram", {
                "name": "Subprogram",
                "options": ["none"] + subprogram_ids,
                "command_topic": TOPIC_PENDING_SUBPROGRAM,
                "state_topic": TOPIC_PENDING_SUBPROGRAM,
                "retain": True,
                "icon": "mdi:subdirectory-arrow-right",
            }),
        ]

    def _button_configs(self):
        return [
            ("power_on", {
                "name": "Power On",
                "command_topic": "display/control/power_on",
                "payload_press": "",
                "icon": "mdi:power",
            }),
            ("start_program", {
                "name": "Start Program",
                "command_topic": "display/control/start",
                "command_template": _START_SWITCH_COMMAND_TEMPLATE,
                "icon": "mdi:play",
            }),
            ("switch_program", {
                "name": "Switch Program",
                "command_topic": "display/control/switch",
                "command_template": _START_SWITCH_COMMAND_TEMPLATE,
                "icon": "mdi:swap-horizontal",
            }),
            ("stop", {
                "name": "Stop",
                "command_topic": "display/control/stop",
                "payload_press": "",
                "icon": "mdi:stop",
            }),
            ("retry", {
                "name": "Retry",
                "command_topic": "display/control/retry",
                "payload_press": "",
                "icon": "mdi:refresh",
            }),
            ("shutdown", {
                "name": "Shutdown",
                "command_topic": "display/control/shutdown",
                "payload_press": "",
                "icon": "mdi:power-off",
            }),
        ]
