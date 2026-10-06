"""Read-only Weltrade position-close reconciliation before supervised signals."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
from pathlib import Path

import MetaTrader5 as mt5

from broker.demo_guard import DemoOnlyGuard
from broker.mt5_gateway import read_mt5_trade_history_snapshot
from broker.scope import enforce_weltrade_only
from core.logger import logger
from execution.persistence import SQLiteIntentRecordStore, SQLitePositionLedger, PositionLedgerEntry
from notifications.events import JQENotificationEvents
from notifications.factory import notification_service_from_settings


def _halt(records: SQLiteIntentRecordStore, reason: str) -> None:
    records.record_post_fill_integrity_halt(reason)
    raise RuntimeError(f"Weltrade close reconciliation halted: {reason}")


async def _alert_unconfirmed(
    ledger: SQLitePositionLedger, events: JQENotificationEvents, row: PositionLedgerEntry,
) -> None:
    if ledger.claim_close_unconfirmed_notification_once(broker="weltrade", position_id=row.position_id):
        try:
            await events.trade_blocked(
                reason="CLOSE_UNCONFIRMED",
                facts={"Symbol": row.symbol, "Position": row.position_id},
            )
        except Exception:
            logger.warning("Weltrade close-unconfirmed alert failed")


async def _send_pending_closes(
    ledger: SQLitePositionLedger, events: JQENotificationEvents, currency: str,
) -> None:
    for row in ledger.pending_close_notifications(broker="weltrade"):
        if not ledger.claim_close_notification_once(broker="weltrade", position_id=row.position_id):
            continue
        facts = {
            "Symbol": row.symbol, "Position": row.position_id,
            "Result": f"{row.realized_pnl:+.2f} {row.currency or currency}" if row.realized_pnl is not None else "",
            "Reason": row.close_reason or "UNKNOWN",
        }
        if row.side:
            facts["Side"] = row.side
        if row.timeframe:
            facts["Timeframe"] = row.timeframe
        if row.close_price is not None:
            facts["Exit"] = str(row.close_price)
        try:
            await events.demo_trade(
                kind="CLOSED", facts=facts,
                event_id=f"CLOSE:{row.position_id}:{row.closed_at}",
                occurred_at=datetime.fromisoformat(row.closed_at),
            )
        except Exception:
            logger.warning("Weltrade closed-trade notification failed")


async def monitor_weltrade_closes(
    settings, *, terminal=mt5, ledger: SQLitePositionLedger | None = None,
    records: SQLiteIntentRecordStore | None = None,
    events: JQENotificationEvents | None = None,
    notify: bool = True,
) -> None:
    """Observe broker positions/deals only; never call an order mutation API."""
    ledger = ledger or SQLitePositionLedger(settings.execution_position_ledger_path)
    records = records or SQLiteIntentRecordStore(settings.intent_store_path)
    events = events or JQENotificationEvents(notification_service_from_settings(settings))
    connected = False
    try:
        enforce_weltrade_only(broker=settings.effective_broker,
                              market_data_source=settings.market_data_source)
        path = settings.weltrade_terminal_path
        login = settings.effective_weltrade_login
        server = settings.effective_weltrade_server
        password = settings.effective_weltrade_password
        if path is None or login is None or not server or not password:
            raise RuntimeError("Weltrade close monitor configuration unavailable")
        connected = terminal.initialize(str(Path(path).resolve())) is True
        if not connected or terminal.login(login, password=password, server=server) is not True:
            raise RuntimeError("Weltrade close monitor connection unavailable")
        account = terminal.account_info()
        info = terminal.terminal_info()
        if (account is None or info is None or getattr(info, "connected", False) is not True
                or getattr(account, "login", None) != login
                or getattr(account, "server", None) != server
                or "WELTRADE" not in str(server).upper()
                or Path(str(getattr(info, "path", ""))).resolve() != Path(path).resolve().parent):
            raise RuntimeError("Weltrade close monitor identity mismatch")
        DemoOnlyGuard.assert_demo_account("weltrade", account)
        positions = terminal.positions_get()
        if positions is None:
            _halt(records, "CLOSE_POSITION_SNAPSHOT_UNAVAILABLE")
        by_ticket = {str(position.ticket): position for position in positions}
        now = datetime.now(timezone.utc)
        for row in ledger.open_entries(broker="weltrade"):
            observed = by_ticket.get(row.position_id)
            if row.volume is None or not math.isfinite(row.volume) or row.volume <= 0:
                try:
                    ledger.mark_close_unconfirmed(broker="weltrade", position_id=row.position_id)
                    if notify:
                        await _alert_unconfirmed(ledger, events, row)
                except Exception:
                    _halt(records, "CLOSE_LEDGER_WRITE_FAILED")
                _halt(records, "CLOSE_UNCONFIRMED")
            observed_volume = None if observed is None else float(observed.volume)
            if observed_volume is not None and math.isclose(observed_volume, row.volume, rel_tol=1e-8, abs_tol=1e-8):
                if row.expected_lifetime_at and now > datetime.fromisoformat(row.expected_lifetime_at):
                    logger.warning("Weltrade position exceeds configured expected lifetime: ticket={}", row.position_id)
                continue
            start = datetime.fromisoformat(row.opened_at) - timedelta(minutes=5)
            history = read_mt5_trade_history_snapshot(
                terminal, start=start, end=now, count=500, connected=True,
            )
            closes = [trade for trade in history.trades if trade.position_id == row.position_id]
            closed_volume = sum(trade.volume for trade in closes)
            expected_closed = row.volume - (observed_volume or 0.0)
            valid = (
                history.covers(start, now) and bool(closes)
                and all(trade.symbol.strip().upper() == row.symbol.strip().upper() for trade in closes)
            )
            valid = (valid and expected_closed > 0
                     and math.isclose(closed_volume, expected_closed, rel_tol=1e-8, abs_tol=1e-8)
                     and all(math.isfinite(trade.profit) and math.isfinite(trade.close_price)
                             and trade.close_price > 0 for trade in closes)
                     and row.position_id in history.position_fees
                     and math.isclose(history.position_open_volume.get(row.position_id, 0.0),
                                      row.volume, rel_tol=1e-8, abs_tol=1e-8))
            if not valid:
                try:
                    ledger.mark_close_unconfirmed(broker="weltrade", position_id=row.position_id)
                    if notify:
                        await _alert_unconfirmed(ledger, events, row)
                except Exception:
                    _halt(records, "CLOSE_LEDGER_WRITE_FAILED")
                _halt(records, "CLOSE_UNCONFIRMED")
            pnl = sum(trade.profit for trade in closes) + history.position_fees[row.position_id]
            last = max(closes, key=lambda trade: trade.closed_at)
            reason = last.close_reason if len({trade.close_reason for trade in closes}) == 1 else "UNKNOWN"
            exit_price = sum(trade.volume * trade.close_price for trade in closes) / closed_volume
            try:
                if observed is None:
                    changed = ledger.mark_closed(
                        broker="weltrade", position_id=row.position_id,
                        closed_at=last.closed_at, close_price=exit_price,
                        realized_pnl=pnl, currency=str(account.currency),
                        reconciliation_state="CLOSE_CONFIRMED", close_reason=reason,
                    )
                    if not changed:
                        raise RuntimeError("Confirmed close ledger row was not updated")
                else:
                    changed = ledger.mark_partial_close(
                        broker="weltrade", position_id=row.position_id,
                        remaining_volume=observed_volume, realized_pnl=pnl,
                    )
                    if not changed:
                        current = next(
                            (item for item in ledger.open_entries(broker="weltrade")
                             if item.position_id == row.position_id), None,
                        )
                        if (current is None or current.remaining_volume is None
                                or current.realized_pnl is None
                                or not math.isclose(current.remaining_volume, observed_volume)
                                or not math.isclose(current.realized_pnl, pnl)):
                            raise RuntimeError("Partial close ledger row was not updated")
            except Exception:
                _halt(records, "CLOSE_LEDGER_WRITE_FAILED")
        try:
            if notify:
                await _send_pending_closes(ledger, events, str(account.currency))
        except Exception:
            _halt(records, "CLOSE_LEDGER_WRITE_FAILED")
        if records.post_fill_integrity_halt() is not None:
            raise RuntimeError("Weltrade persisted integrity halt remains active")
    finally:
        if connected:
            terminal.shutdown()
