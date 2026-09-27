"""Health polling must never signal or stop the observed Windows process."""
import os
import subprocess
import sys
from unittest.mock import patch

import pytest

from core.processes import is_process_alive


@pytest.mark.parametrize("pid", [0, -1, True, None, "123"])
def test_invalid_pid_is_not_probed(pid):
    with patch("core.processes.os.kill") as kill:
        assert is_process_alive(pid) is False
    kill.assert_not_called()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows process API")
def test_windows_current_and_exited_process_are_checked_without_signals():
    with patch("core.processes.os.kill", side_effect=AssertionError("must not send signals")):
        assert is_process_alive(os.getpid()) is True
        process = subprocess.Popen([sys.executable, "-c", "pass"])
        process.wait(timeout=10)
        assert is_process_alive(process.pid) is False
        assert is_process_alive(2**40) is False
