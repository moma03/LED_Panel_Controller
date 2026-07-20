from __future__ import annotations

import json
import queue

from led_controller.commands import State
from led_controller.controller import DisplayController
from led_controller.mqtt_interface import MQTTInterface
from tests.conftest import FakeMQTTClient, make_config


def build_controller(process_terminate_timeout: float = 0.3):
    config = make_config(process_terminate_timeout=process_terminate_timeout)
    client = FakeMQTTClient()
    command_queue: "queue.Queue" = queue.Queue()
    mqtt = MQTTInterface(client, command_queue)
    controller = DisplayController(config, mqtt, command_queue)
    controller.start()
    return controller, client, command_queue


def send(command_queue, command, payload=None):
    command_queue.put((command, payload or {}))


def last_status(client) -> str:
    statuses = [json.loads(p)["state"] for topic, p, _ in client.published if topic == "display/status"]
    return statuses[-1]


def test_startup_publishes_programs_and_off_status():
    controller, client, _ = build_controller()
    assert last_status(client) == "OFF"
    programs_payload = next(p for topic, p, _ in client.published if topic == "display/programs")
    ids = {p["id"] for p in json.loads(programs_payload)}
    assert ids == {"ok", "fail", "trainboard"}


def test_power_on_then_start_reaches_running():
    from led_controller.commands import Command

    controller, client, q = build_controller()
    send(q, Command.POWER_ON)
    controller.step(timeout=0.1)
    assert controller.state == State.IDLE

    send(q, Command.START, {"program": "ok"})
    controller.step(timeout=0.1)
    assert controller.state == State.RUNNING
    assert last_status(client) == "RUNNING"

    controller.request_stop()
    controller._mqtt.stop()


def test_start_replaces_running_program():
    from led_controller.commands import Command

    controller, client, q = build_controller()
    send(q, Command.POWER_ON)
    controller.step(timeout=0.1)
    send(q, Command.START, {"program": "ok"})
    controller.step(timeout=0.1)

    send(q, Command.START, {"program": "trainboard", "subprogram": "berlin"})
    controller.step(timeout=0.1)
    assert controller.state == State.RUNNING
    current_payload = next(
        p for topic, p, _ in reversed(client.published) if topic == "display/current"
    )
    assert json.loads(current_payload) == {"program": "trainboard", "subprogram": "berlin"}


def test_stop_returns_to_idle():
    from led_controller.commands import Command

    controller, _, q = build_controller()
    send(q, Command.POWER_ON)
    controller.step(timeout=0.1)
    send(q, Command.START, {"program": "ok"})
    controller.step(timeout=0.1)

    send(q, Command.STOP)
    controller.step(timeout=0.1)
    assert controller.state == State.IDLE


def test_shutdown_from_idle_reaches_off():
    from led_controller.commands import Command

    controller, _, q = build_controller()
    send(q, Command.POWER_ON)
    controller.step(timeout=0.1)

    send(q, Command.SHUTDOWN)
    controller.step(timeout=0.1)
    assert controller.state == State.OFF


def test_unexpected_exit_triggers_error_state():
    from led_controller.commands import Command

    controller, client, q = build_controller()
    send(q, Command.POWER_ON)
    controller.step(timeout=0.1)
    send(q, Command.START, {"program": "fail"})
    controller.step(timeout=0.1)
    assert controller.state == State.RUNNING  # launched, hasn't exited yet necessarily

    # Give the failing process a moment to exit, then let the loop's health check catch it.
    import time

    time.sleep(0.3)
    controller.step(timeout=0.1)
    assert controller.state == State.ERROR
    errors = [json.loads(p) for topic, p, _ in client.published if topic == "display/errors"]
    assert any("fail" in e["message"] for e in errors)


def test_reset_after_error_force_quits_and_returns_to_idle():
    from led_controller.commands import Command

    controller, _, q = build_controller()
    send(q, Command.POWER_ON)
    controller.step(timeout=0.1)
    send(q, Command.START, {"program": "fail"})
    controller.step(timeout=0.1)

    import time

    time.sleep(0.3)
    controller.step(timeout=0.1)
    assert controller.state == State.ERROR

    send(q, Command.RESET)
    controller.step(timeout=0.1)
    # Reset settles into a stable idle instead of relaunching the program that crashed.
    assert controller.state == State.IDLE
    assert controller._tm.active_program_id is None
    assert controller._tm.last_error is None


def test_invalid_command_is_rejected_and_published():
    from led_controller.commands import Command

    controller, client, q = build_controller()
    # RESET is only valid in ERROR; controller starts in OFF.
    send(q, Command.RESET)
    controller.step(timeout=0.1)
    assert controller.state == State.OFF
    errors = [json.loads(p) for topic, p, _ in client.published if topic == "display/errors"]
    assert any("rejected" in e["message"] for e in errors)


def test_run_forever_stops_foreground_and_relay_on_exit():
    # Ctrl+C / SIGTERM (request_stop()) must leave the display program stopped and
    # the PSU relay off, whether the controller is run interactively during
    # development or as a systemd daemon in production -- not just abandon the loop.
    from led_controller.commands import Command

    controller, _, q = build_controller()
    send(q, Command.POWER_ON)
    controller.step(timeout=0.1)
    send(q, Command.START, {"program": "ok"})
    controller.step(timeout=0.1)
    assert controller._tm._relay.is_on is True

    controller.request_stop()
    controller.run_forever()
    assert controller._tm._relay.is_on is False


def test_unknown_program_is_reported_as_transition_error():
    from led_controller.commands import Command

    controller, client, q = build_controller()
    send(q, Command.POWER_ON)
    controller.step(timeout=0.1)
    send(q, Command.START, {"program": "does-not-exist"})
    controller.step(timeout=0.1)
    assert controller.state == State.ERROR
    errors = [json.loads(p) for topic, p, _ in client.published if topic == "display/errors"]
    assert any("unknown program" in e["message"] for e in errors)
