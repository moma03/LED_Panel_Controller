"""Top-level orchestrator: owns the single-threaded main loop that is the
only place allowed to mutate state, per setup.md's "no command queue, busy
states reject new commands" design goal.

MQTT I/O runs on paho's own network thread and only ever hands commands to
this loop through a thread-safe queue; process exits are detected by polling
once per loop iteration rather than via signals, keeping everything on one
thread and trivially deterministic.
"""

from __future__ import annotations

import queue
import threading

from .commands import Command, State
from .config import AppConfig
from .mqtt_interface import MQTTInterface
from .process_manager import ProcessManager
from .relay import build_relay
from .state_machine import InvalidCommandError, StateMachine
from .transition_manager import TransitionError, TransitionManager


class DisplayController:
    def __init__(
        self,
        config: AppConfig,
        mqtt: MQTTInterface,
        command_queue: "queue.Queue[tuple[Command, dict]]",
        state_machine: StateMachine | None = None,
        process_manager: ProcessManager | None = None,
        transition_manager: TransitionManager | None = None,
    ):
        self._config = config
        self._mqtt = mqtt
        self._queue = command_queue
        self._sm = state_machine or StateMachine()
        self._proc = process_manager or ProcessManager()
        self._tm = transition_manager or TransitionManager(
            config, self._sm, self._proc, build_relay(config.relay.backend, config.relay.pin)
        )
        self._sm.add_listener(self._on_state_change)
        self._stop_event = threading.Event()

    @property
    def state(self) -> State:
        return self._sm.state

    def start(self) -> None:
        self._mqtt.start(self._config.mqtt_host, self._config.mqtt_port)
        self._mqtt.publish_programs(self._config)
        self._mqtt.publish_discovery(self._config)
        self._on_state_change(self._sm.state, self._sm.state)

    def request_stop(self) -> None:
        self._stop_event.set()

    def run_forever(self) -> None:
        self.start()
        try:
            while not self._stop_event.is_set():
                self.step()
        finally:
            self._mqtt.stop()

    def step(self, timeout: float = 0.5) -> None:
        """Processes at most one command, then checks for an unexpected process exit.
        Exposed separately from run_forever so tests can drive the loop deterministically."""
        try:
            command, payload = self._queue.get(timeout=timeout)
        except queue.Empty:
            self._check_health()
            return
        self._check_health()
        self._dispatch(command, payload)

    def _check_health(self) -> None:
        if self._sm.state == State.RUNNING and self._tm.active_program_id is not None:
            exit_code = self._tm.poll_foreground()
            if exit_code is not None:
                self._tm.handle_unexpected_exit(exit_code)

    def _dispatch(self, command: Command, payload: dict) -> None:
        try:
            self._sm.validate(command)
        except InvalidCommandError as exc:
            self._mqtt.publish_error(str(exc))
            return
        try:
            if command is Command.POWER_ON:
                self._tm.power_on()
            elif command is Command.START:
                self._tm.start(payload.get("program"), payload.get("subprogram"))
            elif command is Command.SWITCH:
                self._tm.switch(payload.get("program"), payload.get("subprogram"))
            elif command is Command.STOP:
                self._tm.stop()
            elif command is Command.RETRY:
                self._tm.retry()
            elif command is Command.SHUTDOWN:
                self._tm.shutdown()
        except TransitionError as exc:
            self._mqtt.publish_error(str(exc))

    def _on_state_change(self, _old_state: State, new_state: State) -> None:
        self._mqtt.publish_status(new_state)
        self._mqtt.publish_current(self._tm.active_program_id, self._tm.active_subprogram_id)
        if new_state is State.ERROR and self._tm.last_error is not None:
            self._mqtt.publish_error(self._tm.last_error.message)
