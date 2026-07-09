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
from typing import Protocol

from .commands import Command
from .commands import State as ControllerState
from .config import AppConfig

TOPIC_PROGRAMS = "display/programs"
TOPIC_STATUS = "display/status"
TOPIC_CURRENT = "display/current"
TOPIC_ERRORS = "display/errors"

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

    def _on_connect(self, *_args) -> None:
        for topic in _CONTROL_TOPIC_COMMANDS:
            self._client.subscribe(topic)

    def _on_message(self, _client, _userdata, message) -> None:
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
        self._client.publish(TOPIC_ERRORS, json.dumps({"message": message}))
