"""Orchestrates the transition sequences from setup.md.

Owns the single foreground process (whatever is currently on screen: the idle
animation, a running program, or a transient transition/shutdown animation)
and drives the StateMachine through each sequence. This is the only module
that touches both ProcessManager and RelayController — everything else only
sees the state machine's published state.
"""

from __future__ import annotations

from dataclasses import dataclass

from .commands import State
from .config import AppConfig, ConfigError
from .process_manager import ProcessHandle, ProcessManager
from .relay import RelayController
from .state_machine import StateMachine


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
        self._foreground = self._proc.launch(command)

    def _resolve(self, program_id: str, subprogram_id: str | None) -> str:
        program = self._config.programs.get(program_id)
        if program is None:
            raise TransitionError(f"unknown program {program_id!r}")
        try:
            command = program.resolve_command(subprogram_id)
        except ConfigError as exc:
            raise TransitionError(str(exc)) from exc
        return self._config.render_command(command)

    def _launch_program(self, program_id: str, subprogram_id: str | None) -> None:
        command = self._resolve(program_id, subprogram_id)
        self._foreground = self._proc.launch(command)
        self.active_program_id = program_id
        self.active_subprogram_id = subprogram_id

    # -- sequences ---------------------------------------------------------

    def power_on(self) -> None:
        self._relay.on()
        self._launch_idle()
        self._sm.transition_to(State.IDLE)

    def start(self, program_id: str, subprogram_id: str | None) -> None:
        self._sm.transition_to(State.STARTING)
        self._stop_foreground()
        try:
            self._launch_program(program_id, subprogram_id)
        except TransitionError as exc:
            self._fail(program_id, subprogram_id, str(exc))
            return
        self._sm.transition_to(State.RUNNING)

    def switch(self, program_id: str, subprogram_id: str | None) -> None:
        program = self._config.programs.get(program_id)
        if program is None:
            self._fail(program_id, subprogram_id, f"unknown program {program_id!r}")
            return
        self._sm.transition_to(State.SWITCHING)
        transition_command = self._config.render_command(
            self._config.system.resolve_transition_command(program.name)
        )
        self._proc.run_to_completion(transition_command)
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
        self._proc.run_to_completion(self._config.render_command(self._config.system.shutdown))
        self._stop_foreground()
        self.active_program_id = None
        self.active_subprogram_id = None
        self._relay.off()
        self._sm.transition_to(State.OFF)

    def poll_foreground(self) -> int | None:
        """Returns the foreground process's exit code if it has ended, else None."""
        if self._foreground is None:
            return None
        return self._proc.poll(self._foreground)

    def retry(self) -> None:
        if self.last_error is None:
            raise TransitionError("no previous error to retry")
        program_id, subprogram_id = self.last_error.program_id, self.last_error.subprogram_id
        self.start(program_id, subprogram_id)

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
