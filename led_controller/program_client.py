"""The program's end of the control channel, for Python display programs --
see docs/program-controls.md.

    client = ProgramClient(on_settings=apply_all, on_set=apply_one, on_press=press)
    client.start()                       # no-op when not launched by the hub
    ...
    client.send_state({"status": "ok", "station_name": "Hamburg Hbf"})

Callbacks run on the client's reader thread. Without LED_PANEL_CONTROL_FD in
the environment (started by hand, not by the hub) `active` is False and every
call is a harmless no-op, so a program needs no special case for that.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import threading
from typing import Any, Callable

from .control_channel import ENV_VAR, LineReader, encode


class ProgramClient:
    def __init__(
        self,
        on_settings: Callable[[dict[str, Any]], None] | None = None,
        on_set: Callable[[str, Any], None] | None = None,
        on_press: Callable[[str], None] | None = None,
        fd: int | None = None,
    ):
        self._on_settings = on_settings
        self._on_set = on_set
        self._on_press = on_press
        if fd is None:
            raw = os.environ.get(ENV_VAR, "")
            fd = int(raw) if raw.isdigit() else None
        self._sock: socket.socket | None = None
        if fd is not None:
            try:
                self._sock = socket.socket(fileno=fd)
            except OSError as exc:
                print(f"[program-client] {ENV_VAR}={fd} is not usable: {exc}", file=sys.stderr)
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    @property
    def active(self) -> bool:
        return self._sock is not None

    def start(self) -> None:
        if self._sock is None or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="program-client", daemon=True)
        self._thread.start()

    def send_state(self, values: dict[str, Any]) -> None:
        if self._sock is None:
            return
        try:
            with self._lock:
                self._sock.sendall(encode({"type": "state", "values": values}))
        except OSError as exc:
            print(f"[program-client] could not report state: {exc}", file=sys.stderr)

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self._sock.close()
            self._sock = None

    def _run(self) -> None:
        reader = LineReader()
        while self._sock is not None:
            try:
                data = self._sock.recv(4096)
            except OSError:
                break
            if not data:
                break  # the hub is gone; the program will be stopped anyway
            for message in reader.feed(data):
                self._dispatch(message)

    def _dispatch(self, message: dict) -> None:
        kind = message.get("type")
        try:
            if kind == "settings" and isinstance(message.get("values"), dict):
                if self._on_settings:
                    self._on_settings(message["values"])
            elif kind == "set" and isinstance(message.get("key"), str):
                if self._on_set:
                    self._on_set(message["key"], message.get("value"))
            elif kind == "press" and isinstance(message.get("key"), str):
                if self._on_press:
                    self._on_press(message["key"])
        except Exception as exc:  # a bug in a callback must not end the channel
            print(f"[program-client] error handling {json.dumps(message)}: {exc}", file=sys.stderr)
