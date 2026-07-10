from __future__ import annotations

from led_controller.commands import State
from led_controller.relay import MockRelay
from led_controller.state_machine import StateMachine
from led_controller.transition_manager import LastError, TransitionManager
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


def build(config=None, initial=State.RUNNING):
    config = config or make_config()
    sm = StateMachine(initial=initial)
    proc = RecordingProcessManager()
    relay = MockRelay()
    tm = TransitionManager(config, sm, proc, relay)
    return tm, sm, proc


def test_start_while_running_stops_current_program_first():
    tm, sm, proc = build(initial=State.IDLE)
    tm.start("fail", None)  # launches "fail" as the current foreground program
    assert tm.active_program_id == "fail"

    tm.start("ok", None)  # starting a new program while one is RUNNING replaces it
    assert proc.terminated == ["handle-1"]  # the previous foreground got stopped first
    assert sm.state == State.RUNNING
    assert tm.active_program_id == "ok"
    assert len(proc.launched) == 2


def test_start_to_unknown_program_fails():
    tm, sm, proc = build()
    tm.start("does-not-exist", None)
    assert sm.state == State.ERROR
    assert "unknown program" in tm.last_error.message


def test_start_to_known_program_launches_it():
    tm, sm, proc = build()
    tm.start("ok", None)
    assert sm.state == State.RUNNING
    assert tm.active_program_id == "ok"
    assert len(proc.launched) == 1


def test_subprogram_ignored_for_program_without_subprograms():
    # "ok" has no subprograms; a stray value (e.g. Home Assistant's subprogram select
    # reporting "unknown" while untouched) must not leak into active_subprogram_id.
    tm, sm, proc = build()
    tm.start("ok", "unknown")
    assert sm.state == State.RUNNING
    assert tm.active_subprogram_id is None


def test_subprogram_kept_for_program_with_subprograms():
    tm, sm, proc = build()
    tm.start("trainboard", "berlin")
    assert sm.state == State.RUNNING
    assert tm.active_subprogram_id == "berlin"


def test_reset_after_error_clears_error_and_returns_to_idle():
    tm, sm, proc = build(initial=State.ERROR)
    tm.last_error = LastError(program_id="fail", subprogram_id=None, message="boom")
    tm.active_program_id = "fail"
    tm.reset()
    assert sm.state == State.IDLE
    assert tm.last_error is None
    assert tm.active_program_id is None


def test_reset_does_not_relaunch_the_failed_program():
    tm, sm, proc = build(initial=State.ERROR)
    tm.last_error = LastError(program_id="fail", subprogram_id=None, message="boom")
    tm.reset()
    assert all("fail" not in cmd for cmd in proc.launched)
