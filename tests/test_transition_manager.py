from __future__ import annotations

from led_controller.commands import State
from led_controller.relay import MockRelay
from led_controller.state_machine import StateMachine
from led_controller.transition_manager import _REPO_ROOT, LastError, TransitionManager
from tests.conftest import make_config


class RecordingProcessManager:
    """Stands in for ProcessManager so these tests check TransitionManager's control
    flow (what gets called, in what order) without spawning real subprocesses."""

    def __init__(self):
        self.launched: list[str] = []
        self.run_to_completion_calls: list[str] = []
        self.terminated: list[str] = []
        self.calls: list[str] = []  # ordered log across launch/terminate/run_to_completion
        self.cwds_used: list = []
        self._next_id = 0

    def launch(self, command: str, cwd=None) -> str:
        self._next_id += 1
        handle = f"handle-{self._next_id}"
        self.launched.append(command)
        self.calls.append(f"launch:{command}")
        self.cwds_used.append(cwd)
        return handle

    def poll(self, _handle: str):
        return None

    def terminate(self, handle: str, _timeout: float) -> None:
        self.terminated.append(handle)
        self.calls.append(f"terminate:{handle}")

    def run_to_completion(self, command: str, cwd=None) -> int:
        self.run_to_completion_calls.append(command)
        self.calls.append(f"run_to_completion:{command}")
        self.cwds_used.append(cwd)
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


def test_shutdown_stops_foreground_before_playing_the_animation():
    # The animation and the foreground program both need the matrix hardware, which
    # only one process can hold at a time -- running the animation while the old
    # foreground was still up made it hang forever waiting for a handle that was
    # never coming. The foreground must be stopped first.
    tm, sm, proc = build(initial=State.IDLE)
    tm.start("ok", None)
    proc.calls.clear()

    tm.shutdown()
    terminate_index = proc.calls.index("terminate:handle-1")
    animation_index = next(i for i, c in enumerate(proc.calls) if c.startswith("run_to_completion:"))
    assert terminate_index < animation_index
    assert sm.state == State.OFF


def test_shutdown_turns_off_the_relay():
    tm, sm, proc = build(initial=State.IDLE)
    tm._relay.on()
    tm.shutdown()
    assert tm._relay.is_on is False


def test_emergency_stop_stops_foreground_and_turns_off_relay():
    tm, sm, proc = build(initial=State.IDLE)
    tm.start("ok", None)
    tm._relay.on()

    tm.emergency_stop()
    assert proc.terminated == ["handle-1"]
    assert tm._relay.is_on is False


def test_emergency_stop_is_safe_to_call_with_nothing_running():
    tm, sm, proc = build(initial=State.OFF)
    tm.emergency_stop()  # must not raise
    assert proc.terminated == []
    assert tm._relay.is_on is False


def test_launches_always_use_the_repo_root_as_cwd():
    # Program commands (e.g. "python3 programs/idle.py") are relative to the repo
    # root by convention -- resolving them against whatever cwd the controller
    # process happens to have (e.g. a systemd unit's WorkingDirectory, if set at
    # all) broke every launch as soon as the two didn't match. Every subprocess must
    # get an explicit, correct cwd regardless of the controller's own.
    tm, sm, proc = build(initial=State.IDLE)
    tm.start("ok", None)
    tm.shutdown()
    assert proc.cwds_used
    assert all(cwd == _REPO_ROOT for cwd in proc.cwds_used)
