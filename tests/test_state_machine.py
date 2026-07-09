from __future__ import annotations

import pytest

from led_controller.commands import ALLOWED_COMMANDS, Command, State
from led_controller.state_machine import InvalidCommandError, StateMachine


def test_initial_state_is_off():
    sm = StateMachine()
    assert sm.state == State.OFF


@pytest.mark.parametrize(
    ("state", "command"),
    [(state, command) for state, commands in ALLOWED_COMMANDS.items() for command in commands],
)
def test_allowed_commands_pass_validation(state, command):
    sm = StateMachine(initial=state)
    sm.validate(command)  # should not raise


@pytest.mark.parametrize(
    ("state", "command"),
    [
        (state, command)
        for state in State
        for command in Command
        if command not in ALLOWED_COMMANDS[state]
    ],
)
def test_disallowed_commands_are_rejected(state, command):
    sm = StateMachine(initial=state)
    with pytest.raises(InvalidCommandError):
        sm.validate(command)


def test_transition_notifies_listeners():
    sm = StateMachine(initial=State.OFF)
    seen = []
    sm.add_listener(lambda old, new: seen.append((old, new)))
    sm.transition_to(State.IDLE)
    assert seen == [(State.OFF, State.IDLE)]
    assert sm.state == State.IDLE


def test_transient_states_accept_no_commands():
    for state in (State.STARTING, State.SWITCHING, State.STOPPING, State.SHUTTING_DOWN):
        assert ALLOWED_COMMANDS[state] == frozenset()
