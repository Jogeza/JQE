"""Read-only diagnostic for MetaTrader5 process-global terminal state.

This script never calls order_check, order_send, or any gateway mutation.
It deliberately initializes two terminal installations in one Python process
and reports only terminal paths and boolean comparisons. Account identifiers
are compared in memory and are never printed.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys

import MetaTrader5 as mt5

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from broker.mt5_gateway import MT5Gateway


DERIV_TERMINAL = Path(r"C:\Program Files\Deriv BVI MT5 Terminal\terminal64.exe")
WELTRADE_TERMINAL = Path(r"C:\Program Files\Weltrade MT5 Terminal\terminal64.exe")


def _terminal_snapshot() -> tuple[str, str]:
    info = mt5.terminal_info()
    if info is None:
        raise RuntimeError("terminal_info unavailable")
    return str(getattr(info, "path", "")), str(getattr(info, "data_path", ""))


def _account_snapshot() -> tuple[object, bool]:
    info = mt5.account_info()
    if info is None:
        raise RuntimeError("Account environment unavailable; DEMO confirmation required")
    mode = getattr(info, "trade_mode", None)
    # MT5's explicit DEMO value is integer 0; bools and coercible strings fail.
    if type(mode) is not int or mode != 0:
        raise RuntimeError("Account environment is not explicitly DEMO; audit refused")
    account_id = getattr(info, "login", None)
    if type(account_id) is not int or account_id <= 0:
        raise RuntimeError("Account identity unavailable or malformed; audit refused")
    return account_id, True


def _require_consistent_demo_read(read: object, account_id: object) -> None:
    mode = getattr(read, "trade_mode", None)
    if type(mode) is not str or mode != "demo":
        raise RuntimeError("Gateway account environment is not explicitly DEMO; audit refused")
    if getattr(read, "account_id", None) != str(account_id):
        raise RuntimeError("Account observations conflict; audit refused")


async def main() -> int:
    if os.getenv("JQE_RUN_MT5_PROCESS_GLOBAL_AUDIT") != "1":
        raise RuntimeError("Set JQE_RUN_MT5_PROCESS_GLOBAL_AUDIT=1 to run this read-only diagnostic")

    missing = [str(path) for path in (DERIV_TERMINAL, WELTRADE_TERMINAL) if not path.is_file()]
    if missing:
        raise RuntimeError(f"Required terminal executable missing: {missing}")

    first_handle = MT5Gateway(terminal_path=DERIV_TERMINAL, expected_environment="demo")
    try:
        await first_handle.connect()
        first_initialized = first_handle.is_connected
        first_path, first_data_path = _terminal_snapshot()
        first_account_id, first_is_demo = _account_snapshot()
        first_read = await first_handle.get_account_info()
        _require_consistent_demo_read(first_read, first_account_id)

        second_initialized = bool(mt5.initialize(path=str(WELTRADE_TERMINAL)))
        if not second_initialized:
            raise RuntimeError("Second terminal initialization failed")
        second_path, second_data_path = _terminal_snapshot()
        second_account_id, second_is_demo = _account_snapshot()

        first_handle_after = await first_handle.get_account_info()
        _require_consistent_demo_read(first_handle_after, second_account_id)
        after_path, after_data_path = _terminal_snapshot()

        output = {
            "first_initialized": first_initialized,
            "first_terminal_path": first_path,
            "first_data_path": first_data_path,
            "first_demo_verified": first_is_demo,
            "second_initialized": second_initialized,
            "second_terminal_path": second_path,
            "second_data_path": second_data_path,
            "second_demo_verified": second_is_demo,
            "terminal_path_changed": first_path.casefold() != second_path.casefold(),
            "data_path_changed": first_data_path.casefold() != second_data_path.casefold(),
            "account_identity_changed": first_account_id != second_account_id,
            "first_handle_initial_matches_first_session": first_read.account_id == str(first_account_id),
            "first_handle_after_switch_matches_second_session": first_handle_after.account_id == str(second_account_id),
            "first_handle_after_switch_terminal_path": after_path,
            "first_handle_after_switch_data_path": after_data_path,
        }
        print(json.dumps(output, indent=2))
        return 0
    finally:
        await first_handle.disconnect()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
