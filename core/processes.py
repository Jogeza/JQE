"""Read-only process liveness checks; never send Windows console events."""
from __future__ import annotations

import os
import sys


def is_process_alive(pid: int) -> bool:
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        return False
    if sys.platform == "win32":
        return _windows_process_alive(pid)
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except (ProcessLookupError, ValueError, OverflowError):
        return False
    return True


def _windows_process_alive(pid: int) -> bool:
    import ctypes
    from ctypes import wintypes

    if pid > 0xFFFFFFFF:
        return False
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    # SYNCHRONIZE permits querying exit state without terminate/signal access.
    handle = kernel.OpenProcess(0x00100000, False, pid)
    if not handle:
        return False  # Unreadable state is not evidence of a healthy collector.
    try:
        return kernel.WaitForSingleObject(handle, 0) == 0x00000102  # WAIT_TIMEOUT
    finally:
        kernel.CloseHandle(handle)
