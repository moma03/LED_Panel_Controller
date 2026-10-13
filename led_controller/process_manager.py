"""Launches and terminates programs as plain subprocesses.

The controller never inspects *how* a program is implemented — it only ever
deals with a shell command string, a PID, and an exit code. This is what
makes the controller language-independent per setup.md.
"""

from __future__ import annotations

import os
import shlex
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .control_channel import ControlChannel


@dataclass
class ProcessHandle:
    command: str
    popen: subprocess.Popen


class ProcessManager:
    def launch(self, command: str, cwd: str | Path | None = None,
               channel: ControlChannel | None = None) -> ProcessHandle:
        """`channel`: a program with controls gets its end of the control channel
        as an inherited descriptor, named in its environment (see
        docs/program-controls.md)."""
        if channel is None:
            popen = subprocess.Popen(shlex.split(command), cwd=cwd)
        else:
            popen = subprocess.Popen(shlex.split(command), cwd=cwd,
                                     pass_fds=(channel.child_fd,),
                                     env={**os.environ, **channel.child_env()})
            channel.after_spawn()
        return ProcessHandle(command=command, popen=popen)

    def poll(self, handle: ProcessHandle) -> int | None:
        """Returns the exit code if the process has ended, else None."""
        return handle.popen.poll()

    def terminate(self, handle: ProcessHandle, timeout: float) -> None:
        """Graceful SIGTERM, waits up to `timeout` seconds, then SIGKILL."""
        if handle.popen.poll() is not None:
            return
        handle.popen.send_signal(signal.SIGTERM)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if handle.popen.poll() is not None:
                return
            time.sleep(0.05)
        if handle.popen.poll() is None:
            handle.popen.kill()
            handle.popen.wait()

    def run_to_completion(self, command: str, cwd: str | Path | None = None) -> int:
        """Runs a short-lived command (e.g. a transition animation) and blocks until it exits."""
        return subprocess.run(shlex.split(command), cwd=cwd).returncode
