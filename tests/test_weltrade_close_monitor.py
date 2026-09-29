"""Offline broker-read-only close reconciliation and durable alert proofs."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from broker.types import OrderSide
from config.settings import Settings
from execution.persistence import SQLiteIntentRecordStore, SQLitePositionLedger
from monitoring import weltrade_close_monitor as monitor
from notifications.events import JQENotificationEvents
from notifications.service import NotificationService
from notifications.types import NotificationType


class ReadOnlyTerminal:
    DEAL_ENTRY_IN = 0
    DEAL_ENTRY_OUT = 1
    DEAL_ENTRY_INOUT = 2
    DEAL_TYPE_BUY = 10
    DEAL_TYPE_SELL = 11
    DEAL_TYPE_COMMISSION = 20
    DEAL_TYPE_INTEREST = 21
    DEAL_TYPE_BALANCE = 22
    DEAL_TYPE_CREDIT = 23
    DEAL_TYPE_BONUS = 24
    DEAL_REASON_SL = 30
    DEAL_REASON_TP = 31
    DEAL_REASON_CLIENT = 32
    DEAL_REASON_MOBILE = 33
    DEAL_REASON_WEB = 34

    def __init__(self, path: Path, deals=(), positions=()):
        self.path = path
        self.deals = deals
        self.positions = positions
        self.calls = []

    def initialize(self, path):
        self.calls.append("initialize")
        return path == str(self.path.resolve())

    def login(self, login, *, password, server):
        self.calls.append("login")
        return login == 12345 and password == "offline-only" and server == "Weltrade-Demo"

    def account_info(self):
        self.calls.append("account_info")
        return SimpleNamespace(login=12345, server="Weltrade-Demo", trade_mode=0, currency="USD")

    def terminal_info(self):
        self.calls.append("terminal_info")
        return SimpleNamespace(connected=True, path=str(self.path.parent))

    def positions_get(self):
        self.calls.append("positions_get")
        return self.positions

    def symbol_info_tick(self, symbol):
        self.calls.append("symbol_info_tick")
        return SimpleNamespace(time=int(datetime.now(timezone.utc).timestamp()) + 3 * 3600)

    def history_deals_get(self, start, end):
        self.calls.append("history_deals_get")
        return self.deals

    def shutdown(self):
        self.calls.append("shutdown")


@pytest.fixture
def case(tmp_path, monkeypatch):
    path = tmp_path / "terminal64.exe"
    path.touch()
    settings = Settings(
        _env_file=None, broker="weltrade", market_data_source="broker",
        weltrade_terminal_path=path, weltrade_demo_login=12345,
        weltrade_demo_password="offline-only", weltrade_demo_server="Weltrade-Demo",
        execution_position_ledger_path=tmp_path / "ledger.sqlite3",
        intent_store_path=tmp_path / "intents.sqlite3",
    )
    ledger = SQLitePositionLedger(settings.execution_position_ledger_path)
    opened = datetime.now(timezone.utc) - timedelta(hours=1)
    ledger.record_confirmed_fill_once(
        broker="weltrade", symbol="FX Vol 20", position_id="77", order_id="77",
        side=OrderSide.BUY, volume=1.0, entry_price=100.0, stop_loss=95.0,
        opened_at=opened, timeframe="M5",
    )
    records = SQLiteIntentRecordStore(settings.intent_store_path)
    sink = SimpleNamespace(send=AsyncMock())
    events = JQENotificationEvents(NotificationService(sink))
    terminal = ReadOnlyTerminal(path)
    monkeypatch.setattr(monitor.DemoOnlyGuard, "assert_demo_account", lambda *args: None)
    return settings, ledger, records, events, sink, terminal, opened


def deal(terminal, *, ticket, position_id=77, volume=1.0, entry=None,
         reason=None, profit=2.0, commission=-0.2, swap=-0.05, price=102.0):
    return SimpleNamespace(
        ticket=ticket, position_id=position_id,
        entry=terminal.DEAL_ENTRY_OUT if entry is None else entry,
        type=terminal.DEAL_TYPE_SELL, volume=volume, price=price,
        profit=profit, commission=commission, swap=swap,
        symbol="FX Vol 20", reason=reason,
        time=int(datetime.now(timezone.utc).timestamp()) + 3 * 3600,
    )


async def run_case(case):
    settings, ledger, records, events, _, terminal, _ = case
    await monitor.monitor_weltrade_closes(
        settings, terminal=terminal, ledger=ledger, records=records, events=events,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("reason,expected", [
    (ReadOnlyTerminal.DEAL_REASON_SL, "STOP_LOSS"),
    (ReadOnlyTerminal.DEAL_REASON_TP, "TAKE_PROFIT"),
    (ReadOnlyTerminal.DEAL_REASON_CLIENT, "MANUAL"),
])
async def test_confirmed_close_is_recorded_and_alerted_once_across_restart(case, reason, expected):
    settings, ledger, records, events, sink, terminal, _ = case
    opening = deal(terminal, ticket=1, entry=terminal.DEAL_ENTRY_IN,
                   profit=0.0, commission=-0.1, swap=0.0)
    terminal.deals = (opening, deal(terminal, ticket=2, reason=reason))
    await run_case(case)
    row = ledger.entries()[0]
    assert row.closed_at is not None and row.close_price == 102.0
    assert row.realized_pnl == pytest.approx(1.65)
    assert row.close_reason == expected and row.remaining_volume == 0
    assert row.close_notification_claimed_at is not None
    event = sink.send.await_args.args[0]
    assert event.kind is NotificationType.POSITION_CLOSED
    assert event.facts["Reason"] == expected
    assert event.facts["Result"] == "+1.65 USD"
    restarted = SQLitePositionLedger(settings.execution_position_ledger_path)
    await monitor.monitor_weltrade_closes(settings, terminal=terminal, ledger=restarted,
                                          records=records, events=events)
    assert sink.send.await_count == 1
    assert not hasattr(terminal, "order_send")
    assert not hasattr(terminal, "submit_order")
    assert not hasattr(terminal, "position_close")


@pytest.mark.asyncio
async def test_partial_close_then_complete_close(case):
    _, ledger, _, _, sink, terminal, _ = case
    terminal.positions = (SimpleNamespace(ticket=77, volume=0.4),)
    terminal.deals = (
        deal(terminal, ticket=1, entry=terminal.DEAL_ENTRY_IN,
             profit=0.0, commission=0.0, swap=0.0),
        deal(terminal, ticket=2, volume=0.6, profit=1.2),
    )
    await run_case(case)
    row = ledger.entries()[0]
    assert row.closed_at is None and row.remaining_volume == 0.4
    assert row.realized_pnl == pytest.approx(0.95)
    sink.send.assert_not_awaited()
    terminal.positions = ()
    terminal.deals = (*terminal.deals, deal(terminal, ticket=3, volume=0.4,
                                           profit=0.8, reason=terminal.DEAL_REASON_TP))
    await run_case(case)
    assert ledger.entries()[0].closed_at is not None
    sink.send.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("deals", [(), None])
async def test_missing_or_unavailable_history_halts_and_alerts_once(case, deals):
    _, ledger, records, _, sink, terminal, _ = case
    terminal.deals = deals
    with pytest.raises(RuntimeError, match="CLOSE_UNCONFIRMED"):
        await run_case(case)
    assert ledger.entries()[0].reconciliation_state == "CLOSE_UNCONFIRMED"
    assert ledger.entries()[0].closed_at is None
    assert records.post_fill_integrity_halt() == "CLOSE_UNCONFIRMED"
    with pytest.raises(RuntimeError):
        await run_case(case)
    assert sink.send.await_count == 1


@pytest.mark.asyncio
async def test_ambiguous_volume_halts_without_guessing(case):
    _, ledger, records, _, _, terminal, _ = case
    terminal.deals = (deal(terminal, ticket=2, volume=0.5),)
    with pytest.raises(RuntimeError, match="CLOSE_UNCONFIRMED"):
        await run_case(case)
    assert ledger.entries()[0].close_price is None
    assert records.post_fill_integrity_halt() == "CLOSE_UNCONFIRMED"


@pytest.mark.asyncio
async def test_missing_opening_fee_evidence_halts(case):
    _, ledger, records, _, sink, terminal, _ = case
    terminal.deals = (deal(terminal, ticket=2),)
    with pytest.raises(RuntimeError, match="CLOSE_UNCONFIRMED"):
        await run_case(case)
    assert ledger.entries()[0].closed_at is None
    assert records.post_fill_integrity_halt() == "CLOSE_UNCONFIRMED"
    assert sink.send.await_count == 1


@pytest.mark.asyncio
async def test_notification_failure_keeps_confirmed_ledger_close(case):
    _, ledger, _, _, sink, terminal, _ = case
    terminal.deals = (
        deal(terminal, ticket=1, entry=terminal.DEAL_ENTRY_IN,
             profit=0.0, commission=0.0, swap=0.0),
        deal(terminal, ticket=2, reason=terminal.DEAL_REASON_SL),
    )
    sink.send.side_effect = RuntimeError("offline channel unavailable")
    await run_case(case)
    assert ledger.entries()[0].closed_at is not None
    assert ledger.entries()[0].close_notification_claimed_at is not None
    await run_case(case)
    sink.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_restart_sends_previously_committed_close_once(case):
    settings, ledger, records, events, sink, terminal, _ = case
    closed_at = datetime.now(timezone.utc)
    assert ledger.mark_closed(
        broker="weltrade", position_id="77", closed_at=closed_at,
        close_price=102.0, realized_pnl=1.5, currency="USD",
        reconciliation_state="CLOSE_CONFIRMED", close_reason="STOP_LOSS",
    )
    restarted = SQLitePositionLedger(settings.execution_position_ledger_path)
    await monitor.monitor_weltrade_closes(
        settings, terminal=terminal, ledger=restarted, records=records, events=events,
    )
    await monitor.monitor_weltrade_closes(
        settings, terminal=terminal, ledger=restarted, records=records, events=events,
    )
    assert sink.send.await_count == 1
    assert restarted.entries()[0].close_notification_claimed_at is not None


@pytest.mark.asyncio
async def test_unverified_legacy_close_does_not_generate_alert(case):
    _, ledger, _, _, sink, _, _ = case
    assert ledger.mark_closed(
        broker="weltrade", position_id="77", closed_at=datetime.now(timezone.utc),
        reconciliation_state="LEGACY_UNVERIFIED",
    )
    await run_case(case)
    sink.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_ledger_write_failure_persists_halt(case, monkeypatch):
    _, _, records, _, _, terminal, _ = case
    terminal.deals = (
        deal(terminal, ticket=1, entry=terminal.DEAL_ENTRY_IN,
             profit=0.0, commission=0.0, swap=0.0),
        deal(terminal, ticket=2),
    )
    monkeypatch.setattr(case[1], "mark_closed", MagicMock(side_effect=OSError("disk full")))
    with pytest.raises(RuntimeError, match="CLOSE_LEDGER_WRITE_FAILED"):
        await run_case(case)
    assert records.post_fill_integrity_halt() == "CLOSE_LEDGER_WRITE_FAILED"


@pytest.mark.asyncio
async def test_ledger_update_affecting_no_row_persists_halt(case, monkeypatch):
    _, ledger, records, _, _, terminal, _ = case
    terminal.deals = (
        deal(terminal, ticket=1, entry=terminal.DEAL_ENTRY_IN,
             profit=0.0, commission=0.0, swap=0.0),
        deal(terminal, ticket=2),
    )
    monkeypatch.setattr(ledger, "mark_closed", MagicMock(return_value=False))
    with pytest.raises(RuntimeError, match="CLOSE_LEDGER_WRITE_FAILED"):
        await run_case(case)
    assert records.post_fill_integrity_halt() == "CLOSE_LEDGER_WRITE_FAILED"


@pytest.mark.asyncio
async def test_partial_ledger_update_affecting_no_row_persists_halt(case, monkeypatch):
    _, ledger, records, _, _, terminal, _ = case
    terminal.positions = (SimpleNamespace(ticket=77, volume=0.4),)
    terminal.deals = (
        deal(terminal, ticket=1, entry=terminal.DEAL_ENTRY_IN,
             profit=0.0, commission=0.0, swap=0.0),
        deal(terminal, ticket=2, volume=0.6),
    )
    monkeypatch.setattr(ledger, "mark_partial_close", MagicMock(return_value=False))
    with pytest.raises(RuntimeError, match="CLOSE_LEDGER_WRITE_FAILED"):
        await run_case(case)
    assert records.post_fill_integrity_halt() == "CLOSE_LEDGER_WRITE_FAILED"


@pytest.mark.asyncio
async def test_overdue_open_position_is_reported_without_action(case, monkeypatch):
    _, ledger, _, _, sink, terminal, opened = case
    # Persist an expected lifetime in a separate offline ledger row.
    with ledger._connect() as connection:
        connection.execute("UPDATE live_paper_positions SET expected_lifetime_at=? WHERE position_id='77'",
                           ((opened + timedelta(minutes=1)).isoformat(),))
    terminal.positions = (SimpleNamespace(ticket=77, volume=1.0),)
    warning = MagicMock()
    monkeypatch.setattr(monitor.logger, "warning", warning)
    await run_case(case)
    assert ledger.entries()[0].closed_at is None
    warning.assert_called_once()
    sink.send.assert_not_awaited()
