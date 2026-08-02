"""Shared pytest configuration for the JQE test suite.

``MetaTrader5`` is a Windows-only package and cannot be installed on
Linux/macOS or most CI runners. Several modules (``core.mt5_connection``,
``core.market_data``, ``backtesting.backtest``, ...) import it at module
scope, which would otherwise make those modules — and anything that
transitively imports them, including ``main.py`` — impossible to even
import during testing on non-Windows systems.

Before any test module is collected, this file installs a lightweight
mock in ``sys.modules`` under the name ``MetaTrader5`` *if the real
package is not already installed*. This is purely a test-time shim: it
does not change any production source file or behavior, and on a machine
where the real ``MetaTrader5`` package is present (e.g. Windows CI with
a licensed terminal), the real package is used untouched.

Consolidating this into the broker layer itself (so no module needs the
real or mocked package to be importable at all) is tracked as Milestone
2 — Broker Abstraction.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock


def _install_mt5_stub_if_needed() -> None:
    """Installs a MagicMock stand-in for MetaTrader5 if it isn't installed."""
    try:
        import MetaTrader5  # noqa: F401
    except ImportError:
        mt5_stub = MagicMock(name="MetaTrader5Stub")
        # Commonly-referenced module-level constant used in default
        # arguments (e.g. backtesting/backtest.py); give it a concrete
        # value rather than a MagicMock so equality/typing stays sane.
        mt5_stub.TIMEFRAME_M5 = 5
        sys.modules["MetaTrader5"] = mt5_stub


_install_mt5_stub_if_needed()
