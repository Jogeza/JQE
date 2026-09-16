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
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest


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


@pytest.fixture(autouse=True)
def _fresh_mt5_session_authority(monkeypatch, request):
    """Each test has a fresh process authority; within-test ownership is real."""
    from core.mt5_session import mt5_session

    mt5_session.invalidate()
    if request.module.__name__ == "tests.test_mt5_gateway":
        from tests.mt5_stubs import configure_sdk
        sdk = MagicMock(name="OfflineMT5")
        configure_sdk(sdk)
        monkeypatch.setattr("broker.mt5_gateway.mt5", sdk)
    yield
    mt5_session.invalidate()


@pytest.fixture(autouse=True)
def _offline_main_market_source(monkeypatch, request):
    """Keep orchestration tests offline after market/execution decoupling."""
    if not request.module.__name__.startswith("tests.test_main"):
        return
    import main
    from broker.types import Candle

    class Source:
        async def get_candles(self, symbol, timeframe, count):
            # Fixed historical fixture keeps durable idempotency keys stable.
            anchor = datetime(2026, 8, 29, 12, tzinfo=timezone.utc) - timedelta(
                seconds=3600 * (count - 1)
            )
            return [
                Candle(
                    time=anchor + timedelta(seconds=3600 * index),
                    open=100.0,
                    high=102.0,
                    low=99.0,
                    close=101.0,
                    volume=1.0,
                    source="fixture",
                )
                for index in range(count)
            ]

    @asynccontextmanager
    async def source_factory(settings):
        yield Source(), "fixture"

    monkeypatch.setattr(main, "resolved_market_source", source_factory)
