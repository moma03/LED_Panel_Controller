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
    SWITCHING = "SWITCHING"
    STOPPING = "STOPPING"
    SHUTTING_DOWN = "SHUTTING_DOWN"
    ERROR = "ERROR"


class Command(Enum):
    POWER_ON = "power_on"
    START = "start"
    SWITCH = "switch"
    STOP = "stop"
    RETRY = "retry"
    SHUTDOWN = "shutdown"


# Mirrors the state table in setup.md exactly. States not listed here (STARTING,
# SWITCHING, STOPPING, SHUTTING_DOWN) accept no commands — they're transient and
# busy, so any incoming command is rejected while the controller passes through them.
ALLOWED_COMMANDS: dict[State, frozenset[Command]] = {
    State.OFF: frozenset({Command.POWER_ON}),
    State.IDLE: frozenset({Command.START, Command.SHUTDOWN}),
    State.STARTING: frozenset(),
    State.RUNNING: frozenset({Command.STOP, Command.SWITCH, Command.SHUTDOWN}),
    State.SWITCHING: frozenset(),
    State.STOPPING: frozenset(),
    State.SHUTTING_DOWN: frozenset(),
    State.ERROR: frozenset({Command.RETRY, Command.STOP, Command.SHUTDOWN}),
}


def is_allowed(state: State, command: Command) -> bool:
    return command in ALLOWED_COMMANDS[state]
