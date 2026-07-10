from __future__ import annotations

import sys

from led_controller.config import AppConfig, Program, RelayConfig, Subprogram, SystemConfig

SLEEP_CMD = f'{sys.executable} -c "import time; time.sleep(5)"'
NOOP_CMD = f'{sys.executable} -c "pass"'
FAIL_CMD = f'{sys.executable} -c "import sys; sys.exit(1)"'
IGNORE_SIGTERM_CMD = (
    f'{sys.executable} -c '
    '"import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(5)"'
)


def make_config(process_terminate_timeout: float = 1.0) -> AppConfig:
    programs = {
        "ok": Program(id="ok", name="OK", command=SLEEP_CMD),
        "fail": Program(id="fail", name="Fail", command=FAIL_CMD),
        "trainboard": Program(
            id="trainboard",
            name="Train Board",
            command=f'{sys.executable} -c "import time; time.sleep(5)" # {{subprogram}}',
            subprograms={"berlin": Subprogram(id="berlin", name="Berlin Hbf")},
        ),
    }
    system = SystemConfig(idle=SLEEP_CMD, shutdown=NOOP_CMD)
    relay = RelayConfig(backend="mock", pin=26)
    return AppConfig(
        programs=programs,
        system=system,
        relay=relay,
        mqtt_host="localhost",
        mqtt_port=1883,
        process_terminate_timeout=process_terminate_timeout,
    )


class FakeMQTTMessage:
    def __init__(self, topic: str, payload: str):
        self.topic = topic
        self.payload = payload.encode("utf-8")


class FakeMQTTClient:
    """Duck-types the subset of paho.mqtt.client.Client that MQTTInterface uses."""

    def __init__(self, connect_reason_code: int = 0):
        self.on_connect = None
        self.on_message = None
        self.subscribed_topics: list[str] = []
        self.published: list[tuple[str, str, bool]] = []
        self.connected = False
        self.connect_reason_code = connect_reason_code

    def connect(self, host: str, port: int) -> None:
        self.connected = True

    def loop_start(self) -> None:
        if self.on_connect:
            self.on_connect(self, None, None, self.connect_reason_code)

    def loop_stop(self) -> None:
        pass

    def subscribe(self, topic: str) -> None:
        self.subscribed_topics.append(topic)

    def publish(self, topic: str, payload: str, retain: bool = False) -> None:
        self.published.append((topic, payload, retain))

    def inject_message(self, topic: str, payload: dict | None = None) -> None:
        import json

        raw = json.dumps(payload) if payload is not None else ""
        self.on_message(self, None, FakeMQTTMessage(topic, raw))
