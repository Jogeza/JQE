"""Offline coverage proofs for the shared Weltrade daily-history reader."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import broker.mt5_gateway as gateway_module
from broker.mt5_gateway import MT5Gateway, read_mt5_trade_history_snapshot
from execution.safety import DailyStateAuthority
from tests.test_read_only_execution_safety_evaluator import ReadOnlyTerminal, _settings
from tools import evaluate_execution_safety as preflight


class HistoryTerminal:
    DEAL_ENTRY_OUT = 1
    DEAL_ENTRY_INOUT = 2
    DEAL_TYPE_BUY = 3
    DEAL_TYPE_SELL = 4
    DEAL_TYPE_COMMISSION = 5
    DEAL_TYPE_INTEREST = 6
    DEAL_TYPE_BALANCE = 7
    DEAL_TYPE_CREDIT = 8
    DEAL_TYPE_BONUS = 9

    def __init__(self, result=(), *, tick=True):
        self.result = result
        self.tick = tick
        self.window = None

    def symbol_info_tick(self, symbol):
        assert symbol == "FX Vol 20"
        return (SimpleNamespace(time=int(datetime.now(timezone.utc).timestamp()) + 3 * 3600)
                if self.tick else None)

    def history_deals_get(self, start, end):
        self.window = (start, end)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _window():
    end = datetime.now(timezone.utc) - timedelta(seconds=1)
    return end.replace(hour=0, minute=0, second=0, microsecond=0), end


def test_full_window_is_authoritative_and_starts_at_server_day() -> None:
    terminal = HistoryTerminal()
    start, end = _window()
    snapshot = read_mt5_trade_history_snapshot(
        terminal, start=start, end=end, count=500, connected=True,
    )
    assert snapshot.covers(start, end)
    assert terminal.window[0] <= start
    assert terminal.window[0].hour == 21  # Weltrade server midnight at UTC+3.


@pytest.mark.parametrize("result", [None, RuntimeError("offline history failure")])
def test_missing_or_failed_history_is_not_authoritative(result) -> None:
    start, end = _window()
    snapshot = read_mt5_trade_history_snapshot(
        HistoryTerminal(result), start=start, end=end, count=500, connected=True,
    )
    assert not snapshot.covers(start, end)


def test_truncation_is_not_authoritative() -> None:
    start, end = _window()
    deal = SimpleNamespace(entry=HistoryTerminal.DEAL_ENTRY_OUT, type=HistoryTerminal.DEAL_TYPE_BUY)
    snapshot = read_mt5_trade_history_snapshot(
        HistoryTerminal([deal, deal]), start=start, end=end, count=1, connected=True,
    )
    assert snapshot.completeness.value == "TRUNCATED"
    assert not snapshot.covers(start, end)


def test_uninitialized_offset_unknown_and_partial_window_fail_closed() -> None:
    start, end = _window()
    for terminal, connected, begin, finish in (
        (HistoryTerminal(), False, start, end),
        (HistoryTerminal(tick=False), True, start, end),
        (HistoryTerminal(), True, end, start),
        (HistoryTerminal(), True, start, datetime.now(timezone.utc) + timedelta(minutes=1)),
    ):
        assert not read_mt5_trade_history_snapshot(
            terminal, start=begin, end=finish, count=500, connected=connected,
        ).covers(start, end)


@pytest.mark.asyncio
@pytest.mark.parametrize("history_available", [True, False])
async def test_gateway_and_preflight_agree_on_same_mocked_history(
    tmp_path, monkeypatch, history_available,
) -> None:
    settings = _settings(tmp_path)
    terminal = ReadOnlyTerminal(settings.weltrade_terminal_path)
    if not history_available:
        terminal.history_deals_get = lambda start, end: None
    monkeypatch.setattr(preflight.DemoOnlyGuard, "assert_demo_account", lambda *args: None)
    monkeypatch.setattr(gateway_module, "mt5", terminal)
    gateway = MT5Gateway()
    monkeypatch.setattr(gateway, "_require_connected", lambda: None)
    start, end = _window()
    live_history = await gateway.get_trade_history_snapshot(start=start, end=end, count=500)
    evaluation = preflight.evaluate(settings, terminal=terminal)
    assert live_history.covers(start, end) is history_available
    assert (evaluation.daily_state_authority is DailyStateAuthority.AUTHORITATIVE) is history_available


@pytest.mark.asyncio
async def test_gateway_uninitialized_returns_unknown(monkeypatch) -> None:
    gateway = MT5Gateway()
    monkeypatch.setattr(gateway, "_require_connected", lambda: (_ for _ in ()).throw(
        gateway_module.BrokerConnectionError("uninitialized")))
    start, end = _window()
    assert not (await gateway.get_trade_history_snapshot(start=start, end=end)).covers(start, end)
