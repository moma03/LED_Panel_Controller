"""Guarded state store: validates commands against the current state and
notifies listeners on every transition. Contains no business logic — the
actual work of a transition (starting/stopping processes, driving the relay)
lives in TransitionManager.
"""

from __future__ import annotations

from typing import Callable

from .commands import Command, State, is_allowed


class InvalidCommandError(Exception):
    """Raised when a command is not accepted in the current state."""

    def __init__(self, command: Command, state: State):
        self.command = command
        self.state = state
        super().__init__(f"command {command.value!r} rejected in state {state.value}")


StateListener = Callable[[State, State], None]  # (old_state, new_state)


class StateMachine:
    def __init__(self, initial: State = State.OFF):
        self._state = initial
        self._listeners: list[StateListener] = []

    @property
    def state(self) -> State:
        return self._state

    def add_listener(self, listener: StateListener) -> None:
        self._listeners.append(listener)

    def validate(self, command: Command) -> None:
        if not is_allowed(self._state, command):
            raise InvalidCommandError(command, self._state)

    def transition_to(self, new_state: State) -> None:
        old_state = self._state
        self._state = new_state
        for listener in self._listeners:
            listener(old_state, new_state)
