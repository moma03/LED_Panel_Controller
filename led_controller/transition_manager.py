"""Orchestrates the transition sequences from setup.md.

Owns the single foreground process (whatever is currently on screen: the idle
animation, a running program, or a transient transition/shutdown animation)
and drives the StateMachine through each sequence. This is the only module
that touches both ProcessManager and RelayController — everything else only
sees the state machine's published state.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .commands import State
from .config import AppConfig, ConfigError, Program
from .process_manager import ProcessHandle, ProcessManager
from .relay import RelayController
from .state_machine import StateMachine

# Program commands in config.yaml (e.g. "python3 programs/idle.py") are written
# relative to the repo root by convention -- see README.md. Resolving that relative
# path against whatever cwd the *controller* happened to be started with (its
# systemd unit's WorkingDirectory, an interactive shell, cron, ...) only works if
# that cwd happens to match the repo root; get it wrong (or omit it, which is easy to
# do when hand-writing a unit file) and every launch fails with "No such file or
# directory" despite the config being completely correct. Anchoring explicitly to
# this package's own location instead -- two directories up from
# led_controller/transition_manager.py is the repo root that "programs/" is relative
# to -- makes it correct regardless of the controller process's own cwd.
_REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class LastError:
    program_id: str
    subprogram_id: str | None
    message: str


class TransitionError(Exception):
    """Raised when a requested program/subprogram can't be resolved or launched."""


class TransitionManager:
    def __init__(
        self,
        config: AppConfig,
        state_machine: StateMachine,
        process_manager: ProcessManager,
        relay: RelayController,
    ):
        self._config = config
        self._sm = state_machine
        self._proc = process_manager
        self._relay = relay

        self._foreground: ProcessHandle | None = None
        self.active_program_id: str | None = None
        self.active_subprogram_id: str | None = None
        self.last_error: LastError | None = None

    # -- helpers ---------------------------------------------------------

    def _stop_foreground(self) -> None:
        if self._foreground is not None:
            self._proc.terminate(self._foreground, self._config.process_terminate_timeout)
            self._foreground = None

    def _launch_idle(self) -> None:
        command = self._config.render_command(self._config.system.idle)
        self._foreground = self._proc.launch(command, cwd=_REPO_ROOT)

    def _resolve(self, program_id: str, subprogram_id: str | None) -> tuple[Program, str]:
        # program_id/subprogram_id may be either the config id or the display `name`
        # -- Home Assistant's selects show the name, other MQTT clients may send the
        # id directly, and Program/AppConfig.resolve_* accept either.
        program = self._config.resolve_program(program_id)
        if program is None:
            raise TransitionError(f"unknown program {program_id!r}")
        try:
            command = program.resolve_command(subprogram_id)
        except ConfigError as exc:
            raise TransitionError(str(exc)) from exc
        return program, self._config.render_command(command)

    def _launch_program(self, program_id: str, subprogram_id: str | None) -> None:
        program, command = self._resolve(program_id, subprogram_id)
        self._foreground = self._proc.launch(command, cwd=_REPO_ROOT)
        self.active_program_id = program.id
        # A program with no subprograms has no such concept, no matter what a caller
        # passed in -- e.g. Home Assistant's subprogram select reports "unknown" while
        # untouched, and that shouldn't leak into display/current for e.g. Weather.
        # Canonicalize to the subprogram's id (not whatever the caller sent) so
        # display/current is consistent regardless of whether the caller sent an id
        # or a display name.
        resolved_subprogram = program.resolve_subprogram(subprogram_id)
        self.active_subprogram_id = resolved_subprogram.id if resolved_subprogram else None

    # -- sequences ---------------------------------------------------------

    def power_on(self) -> None:
        self._relay.on()
        self._launch_idle()
        self._sm.transition_to(State.IDLE)

    def start(self, program_id: str, subprogram_id: str | None) -> None:
        """Starts `program_id`, stopping whatever is currently in the foreground first
        (the idle animation from IDLE, or the active program from RUNNING) -- there's
        no separate switch sequence, starting a new program while one is already
        running just means the old one stops and the new one starts."""
        self._sm.transition_to(State.STARTING)
        self._stop_foreground()
        try:
            self._launch_program(program_id, subprogram_id)
        except TransitionError as exc:
            self._fail(program_id, subprogram_id, str(exc))
            return
        self._sm.transition_to(State.RUNNING)

    def stop(self) -> None:
        self._sm.transition_to(State.STOPPING)
        self._stop_foreground()
        self.active_program_id = None
        self.active_subprogram_id = None
        self._launch_idle()
        self._sm.transition_to(State.IDLE)

    def shutdown(self) -> None:
        self._sm.transition_to(State.SHUTTING_DOWN)
        # Stop whatever's on the matrix *before* running the shutdown animation --
        # rpi-rgb-led-matrix owns the hardware exclusively, so launching the shutdown
        # animation while the idle/active program still has it initialized (RGBMatrix
        # is a singleton-ish hardware resource, not something two processes can share)
        # left the animation process hanging forever waiting for a hardware handle
        # that was never coming. Same class of bug the old SWITCH command had.
        self._stop_foreground()
        self.active_program_id = None
        self.active_subprogram_id = None
        self._proc.run_to_completion(self._config.render_command(self._config.system.shutdown), cwd=_REPO_ROOT)
        self._relay.off()
        self._sm.transition_to(State.OFF)

    def emergency_stop(self) -> None:
        """Called when the controller process itself is exiting (Ctrl+C, SIGTERM from
        systemd) rather than via an MQTT Shutdown command -- stops whatever's in the
        foreground and de-energizes the relay immediately, skipping the goodbye
        animation entirely so the process can exit right away instead of blocking on
        one more subprocess. Safe to call redundantly (e.g. after a normal shutdown()
        already ran): stopping an already-stopped foreground and switching an
        already-off relay off again are both no-ops."""
        self._stop_foreground()
        self._relay.off()

    def poll_foreground(self) -> int | None:
        """Returns the foreground process's exit code if it has ended, else None."""
        if self._foreground is None:
            return None
        return self._proc.poll(self._foreground)

    def reset(self) -> None:
        """Force-quits whatever's in the foreground (the crashed program is normally
        already gone by the time we're in ERROR -- see _fail -- but this doesn't
        assume that) and settles into a stable IDLE, clearing the error rather than
        relaunching the program that just failed."""
        self._stop_foreground()
        self.active_program_id = None
        self.active_subprogram_id = None
        self.last_error = None
        self._launch_idle()
        self._sm.transition_to(State.IDLE)

    def handle_unexpected_exit(self, exit_code: int) -> None:
        """Called by the controller loop when the foreground program dies on its own."""
        program_id = self.active_program_id
        subprogram_id = self.active_subprogram_id
        message = f"program {program_id!r} exited unexpectedly with code {exit_code}"
        self._foreground = None
        self._fail(program_id, subprogram_id, message)

    def _fail(self, program_id: str | None, subprogram_id: str | None, message: str) -> None:
        self.last_error = LastError(program_id=program_id, subprogram_id=subprogram_id, message=message)
        self.active_program_id = None
        self.active_subprogram_id = None
        self._stop_foreground()
        self._launch_idle()
        self._sm.transition_to(State.ERROR)
