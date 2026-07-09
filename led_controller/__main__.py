"""Entrypoint: load config, wire up the controller, run until interrupted."""

from __future__ import annotations

import argparse
import queue
import signal
import sys

import paho.mqtt.client as mqtt

from .config import ConfigError, load_config
from .controller import DisplayController
from .mqtt_interface import MQTTInterface


def main() -> None:
    parser = argparse.ArgumentParser(description="LED Display Controller")
    parser.add_argument(
        "--config", default="config/config.example.yaml", help="Path to the YAML config file"
    )
    args = parser.parse_args()

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
    command_queue: "queue.Queue" = queue.Queue()
    mqtt_interface = MQTTInterface(client, command_queue)
    controller = DisplayController(config, mqtt_interface, command_queue)

    def _handle_signal(_signum, _frame):
        controller.request_stop()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    controller.run_forever()


if __name__ == "__main__":
    main()
