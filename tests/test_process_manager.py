from __future__ import annotations

import sys
import time

from led_controller.process_manager import ProcessManager
from tests.conftest import IGNORE_SIGTERM_CMD, NOOP_CMD, SLEEP_CMD


def test_launch_and_poll_running_process():
    pm = ProcessManager()
    handle = pm.launch(SLEEP_CMD)
    try:
        assert pm.poll(handle) is None
    finally:
        pm.terminate(handle, timeout=1.0)


def test_poll_returns_exit_code_after_completion():
    pm = ProcessManager()
    handle = pm.launch(NOOP_CMD)
    handle.popen.wait(timeout=5)
    assert pm.poll(handle) == 0


def test_terminate_graceful_shutdown():
    pm = ProcessManager()
    handle = pm.launch(SLEEP_CMD)
    start = time.monotonic()
    pm.terminate(handle, timeout=2.0)
    elapsed = time.monotonic() - start
    assert pm.poll(handle) is not None
    assert elapsed < 2.0  # SIGTERM should end it quickly, not need the full timeout


def test_terminate_force_kills_after_timeout():
    pm = ProcessManager()
    handle = pm.launch(IGNORE_SIGTERM_CMD)
    time.sleep(0.2)  # let the child install its SIGTERM handler before we signal it
    start = time.monotonic()
    pm.terminate(handle, timeout=0.3)
    elapsed = time.monotonic() - start
    assert pm.poll(handle) is not None
    assert elapsed >= 0.3


def test_run_to_completion_returns_exit_code():
    pm = ProcessManager()
    assert pm.run_to_completion(NOOP_CMD) == 0


def _check_cwd_cmd(expected: str) -> str:
    return f'{sys.executable} -c "import os,sys; sys.exit(0 if os.getcwd() == sys.argv[1] else 1)" {expected}'


def test_launch_respects_explicit_cwd(tmp_path):
    # Program commands are relative paths (e.g. "programs/idle.py") by convention --
    # they must be resolved against the cwd passed in here, not whatever cwd this
    # process itself happens to be running with.
    pm = ProcessManager()
    handle = pm.launch(_check_cwd_cmd(str(tmp_path)), cwd=tmp_path)
    assert handle.popen.wait(timeout=5) == 0


def test_run_to_completion_respects_explicit_cwd(tmp_path):
    pm = ProcessManager()
    assert pm.run_to_completion(_check_cwd_cmd(str(tmp_path)), cwd=tmp_path) == 0
