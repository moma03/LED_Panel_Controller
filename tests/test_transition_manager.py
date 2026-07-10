from __future__ import annotations

from led_controller.commands import State
from led_controller.relay import MockRelay
from led_controller.state_machine import StateMachine
from led_controller.transition_manager import TransitionManager
from tests.conftest import make_config


class RecordingProcessManager:
    """Stands in for ProcessManager so these tests check TransitionManager's control
    flow (what gets called, in what order) without spawning real subprocesses."""

    def __init__(self):
        self.launched: list[str] = []
        self.run_to_completion_calls: list[str] = []
        self.terminated: list[str] = []
        self._next_id = 0

    def launch(self, command: str) -> str:
        self._next_id += 1
        handle = f"handle-{self._next_id}"
        self.launched.append(command)
        return handle

    def poll(self, _handle: str):
        return None

    def terminate(self, handle: str, _timeout: float) -> None:
        self.terminated.append(handle)

    def run_to_completion(self, command: str) -> int:
        self.run_to_completion_calls.append(command)
        return 0


def build(config=None):
    config = config or make_config()
    sm = StateMachine(initial=State.RUNNING)
    proc = RecordingProcessManager()
    relay = MockRelay()
    tm = TransitionManager(config, sm, proc, relay)
    return tm, sm, proc


def test_switch_to_unknown_program_fails_without_playing_transition():
    tm, sm, proc = build()
    tm.switch("does-not-exist", None)
    assert sm.state == State.ERROR
    assert proc.run_to_completion_calls == []  # no wasted animation for a bogus program
    assert "unknown program" in tm.last_error.message


def test_switch_resolves_program_placeholder_in_transition_command():
    config = make_config()
    config = config.__class__(
        programs=config.programs,
        system=config.system.__class__(
            idle=config.system.idle,
            transition='echo "{program}"',
            shutdown=config.system.shutdown,
        ),
        relay=config.relay,
        mqtt_host=config.mqtt_host,
        mqtt_port=config.mqtt_port,
        process_terminate_timeout=config.process_terminate_timeout,
    )
    tm, sm, proc = build(config)
    tm.switch("ok", None)
    assert proc.run_to_completion_calls == ['echo "OK"']
    assert sm.state == State.RUNNING


def test_switch_to_known_program_launches_it():
    tm, sm, proc = build()
    tm.switch("ok", None)
    assert sm.state == State.RUNNING
    assert tm.active_program_id == "ok"
    assert len(proc.launched) == 1
