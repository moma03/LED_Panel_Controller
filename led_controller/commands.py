"""State and command vocabulary shared by the whole controller.

This is the single source of truth for the state machine defined in setup.md —
every other module imports State/Command from here rather than redefining them.
"""

from __future__ import annotations

from enum import Enum


class State(Enum):
    OFF = "OFF"
    IDLE = "IDLE"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    SHUTTING_DOWN = "SHUTTING_DOWN"
    ERROR = "ERROR"


class Command(Enum):
    POWER_ON = "power_on"
    START = "start"
    STOP = "stop"
    RESET = "reset"
    SHUTDOWN = "shutdown"


# Mirrors the state table in setup.md exactly. States not listed here (STARTING,
# STOPPING, SHUTTING_DOWN) accept no commands — they're transient and busy, so any
# incoming command is rejected while the controller passes through them.
ALLOWED_COMMANDS: dict[State, frozenset[Command]] = {
    State.OFF: frozenset({Command.POWER_ON}),
    State.IDLE: frozenset({Command.START, Command.SHUTDOWN}),
    State.STARTING: frozenset(),
    # Starting a program while one is already RUNNING just stops the current one
    # and starts the new one -- there's no separate "switch" state for this.
    State.RUNNING: frozenset({Command.START, Command.STOP, Command.SHUTDOWN}),
    State.STOPPING: frozenset(),
    State.SHUTTING_DOWN: frozenset(),
    State.ERROR: frozenset({Command.RESET, Command.STOP, Command.SHUTDOWN}),
}


def is_allowed(state: State, command: Command) -> bool:
    return command in ALLOWED_COMMANDS[state]
