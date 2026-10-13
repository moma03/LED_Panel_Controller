"""The hub's end of a program's control channel -- see docs/program-controls.md.

A Unix socket pair: one end stays here, the other is inherited by the program
(and through it by any wrapper script) as the descriptor named in
LED_PANEL_CONTROL_FD. Messages are JSON objects, one per line, both ways.

A single socket object is shared by the reader thread and senders. It has a
timeout, so a program that never reads its end cannot block whoever sends
(the MQTT thread, for a change from Home Assistant): the send fails, is
logged, and the program simply misses that update.
"""

from __future__ import annotations

import json
import socket
import sys
import threading
from typing import Callable

ENV_VAR = "LED_PANEL_CONTROL_FD"
MAX_LINE_BYTES = 64 * 1024
_SEND_TIMEOUT_SECONDS = 2.0


class LineReader:
    """Splits a byte stream into JSON objects, one per line. Shared with
    program_client.py so both ends agree on framing and limits."""

    def __init__(self) -> None:
        self._buf = b""

    def feed(self, data: bytes) -> list[dict]:
        self._buf += data
        messages = []
        while b"\n" in self._buf:
            line, self._buf = self._buf.split(b"\n", 1)
            message = _decode(line)
            if message is not None:
                messages.append(message)
        if len(self._buf) > MAX_LINE_BYTES:
            print(f"[control-channel] dropping a line longer than {MAX_LINE_BYTES} bytes",
                  file=sys.stderr)
            self._buf = b""
        return messages


def _decode(line: bytes) -> dict | None:
    line = line.strip()
    if not line:
        return None
    try:
        message = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        print(f"[control-channel] ignoring malformed line: {exc}", file=sys.stderr)
        return None
    if not isinstance(message, dict):
        print("[control-channel] ignoring a line that is not a JSON object", file=sys.stderr)
        return None
    return message


def encode(message: dict) -> bytes:
    return (json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


class ControlChannel:
    def __init__(self) -> None:
        self._sock, self._child = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.settimeout(_SEND_TIMEOUT_SECONDS)
        self._send_lock = threading.Lock()
        self._closed = threading.Event()
        self._thread: threading.Thread | None = None

    # -- launch --------------------------------------------------------------

    @property
    def child_fd(self) -> int:
        return self._child.fileno()

    def child_env(self) -> dict[str, str]:
        return {ENV_VAR: str(self.child_fd)}

    def after_spawn(self) -> None:
        """The child has its own copy now; ours would keep the channel open
        after the program exits, hiding that it went away."""
        self._child.close()

    # -- traffic -------------------------------------------------------------

    def start(self, on_message: Callable[[dict], None], on_close: Callable[[], None] | None = None) -> None:
        def run() -> None:
            reader = LineReader()
            try:
                while not self._closed.is_set():
                    try:
                        data = self._sock.recv(4096)
                    except socket.timeout:
                        continue
                    except OSError:
                        break
                    if not data:
                        break
                    for message in reader.feed(data):
                        try:
                            on_message(message)
                        except Exception as exc:  # a bad message must not kill the reader
                            print(f"[control-channel] error handling {message!r}: {exc}",
                                  file=sys.stderr)
            finally:
                if not self._closed.is_set() and on_close is not None:
                    on_close()

        self._thread = threading.Thread(target=run, name="control-channel", daemon=True)
        self._thread.start()

    def send(self, message: dict) -> bool:
        if self._closed.is_set():
            return False
        try:
            with self._send_lock:
                self._sock.sendall(encode(message))
            return True
        except OSError as exc:  # includes socket.timeout and a program that has exited
            print(f"[control-channel] could not send {message.get('type')!r}: {exc}",
                  file=sys.stderr)
            return False

    def close(self) -> None:
        if self._closed.is_set():
            return
        self._closed.set()
        try:
            self._sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self._sock.close()
        if self._child.fileno() != -1:
            self._child.close()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=2.0)
