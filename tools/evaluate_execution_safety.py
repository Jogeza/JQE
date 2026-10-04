"""Read-only Weltrade demo preflight; never creates an order or executor.

Run with ``python -m tools.evaluate_execution_safety``. The persisted result is
deliberately BLOCKED: a preflight has no signal, stop-loss, broker-sized
quantity, or durable reservation and cannot authorize a submission.
"""

from __future__ import annotations

from datetime import datetime, time, timezone
import json
import math
from pathlib import Path
import sqlite3

import MetaTrader5 as mt5

from broker.demo_guard import DemoOnlyGuard
from broker.mt5_gateway import read_mt5_trade_history_snapshot
from broker.scope import enforce_weltrade_only
from config.settings import Settings
from execution.position_limits import demo_position_cap
from execution.safety import (
    DailyStateAuthority, EmergencyStopState, ExecutionAuthorization,
    ExecutionMode, ExecutionSafetySnapshot, RiskAuthorizationSnapshot,
    RiskEvaluationState, SQLiteExecutionSafetyStore,
)
from risk.risk_engine import MAX_RISK_PERCENT, RiskEngine


def _read_rows(path: Path, query: str, args: tuple[object, ...] = ()) -> list[tuple]:
    if not path.is_file():
        raise ValueError("Required durable safety store is missing")
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=3) as conn:
        return conn.execute(query, args).fetchall()


def _daily_cap_state(settings: Settings, account_id: str, at: datetime) -> tuple[bool, int, int]:
    pairs = _read_rows(
        Path(settings.watchlist_store_path),
        "SELECT DISTINCT upper(symbol) FROM watchlist",
    )
    if not pairs:
        raise ValueError("Watchlist is empty")
    scope = f"weltrade:{account_id}"
    rows = _read_rows(
        Path(settings.daily_instrument_trade_store_path),
        "SELECT instrument, submission_starts FROM daily_instrument_trade_counter "
        "WHERE scope=? AND utc_date=?",
        (scope, at.date().isoformat()),
    )
    usage = {str(symbol).upper(): int(count) for symbol, count in rows}
    maximum = max(usage.get(str(symbol), 0) for (symbol,) in pairs)
    return maximum < settings.max_daily_trades_per_instrument, maximum, len(pairs)


def _unresolved_count(settings: Settings) -> int:
    rows = _read_rows(
        Path(settings.intent_store_path),
        "SELECT count(*) FROM intent_records WHERE state IN ('PENDING','UNKNOWN')",
    )
    return int(rows[0][0])


def _publish_evidence(
    settings: Settings, *, at: datetime, trade_mode: int | None,
    balance: float | None, equity: float | None, currency: str | None,
    daily_count: int | None, daily_loss: float | None,
    cap_count: int | None, cap_symbols: int | None,
    reasons: list[str], authority: DailyStateAuthority,
    unresolved: int, account_id: str | None,
) -> ExecutionSafetySnapshot:
    store = SQLiteExecutionSafetyStore(settings.execution_safety_store_path, initialize=True)
    snapshot = ExecutionSafetySnapshot(
        observed_at=at, emergency_stop_state=settings.emergency_stop,
        execution_mode=ExecutionMode.DURABLE, broker="weltrade",
        environment=settings.environment, durable_executor_enabled=False,
        daily_state_authority=authority, unresolved_intent_count=unresolved,
        unresolved_intent_blocked=unresolved > 0,
        execution_authorization=ExecutionAuthorization.BLOCKED,
        reason_codes=tuple(dict.fromkeys([*reasons, "READ_ONLY_PREFLIGHT_NO_ORDER_INTENT"])),
    )
    store.publish(snapshot)
    risk_state = RiskEvaluationState.BLOCKED if account_id else RiskEvaluationState.UNKNOWN
    store.publish_risk(RiskAuthorizationSnapshot(
        observed_at=at, broker="weltrade", environment=settings.environment,
        account_id=account_id, evaluation_state=risk_state,
        balance=balance, equity=equity, currency=currency,
        max_daily_loss=settings.max_daily_loss,
        max_trades_daily=settings.max_trades_daily,
        daily_trades_count=daily_count, daily_loss_percent=daily_loss,
        risk_allowed=False, risk_message="Read-only preflight cannot authorize a trade",
        rejection_reason="; ".join(snapshot.reason_codes),
        authorized_risk_amount=None, authorized_risk_percent=None,
        execution_quantity_available=False, execution_quantity_value=None,
        execution_quantity_unit=None,
        execution_quantity_reason="No signal, stop-loss, or broker-sized quantity evaluated",
    ))
    with sqlite3.connect(Path(settings.execution_safety_store_path), timeout=5) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS read_only_preflight (
            singleton_id INTEGER PRIMARY KEY CHECK(singleton_id=1),
            observed_at TEXT NOT NULL, broker TEXT NOT NULL,
            demo_trade_mode INTEGER, emergency_stop TEXT NOT NULL,
            balance REAL, equity REAL, currency TEXT,
            configured_risk_percent REAL NOT NULL, policy_risk_cap_percent REAL NOT NULL,
            daily_trades_count INTEGER, daily_loss_percent REAL,
            max_daily_trades INTEGER NOT NULL, max_daily_loss_percent REAL NOT NULL,
            maximum_instrument_cap_usage INTEGER, instrument_cap_limit INTEGER NOT NULL,
            watchlist_symbols INTEGER, reason_codes TEXT NOT NULL
        )""")
        conn.execute("""INSERT INTO read_only_preflight VALUES
            (1,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(singleton_id) DO UPDATE SET
            observed_at=excluded.observed_at, broker=excluded.broker,
            demo_trade_mode=excluded.demo_trade_mode,
            emergency_stop=excluded.emergency_stop, balance=excluded.balance,
            equity=excluded.equity, currency=excluded.currency,
            configured_risk_percent=excluded.configured_risk_percent,
            policy_risk_cap_percent=excluded.policy_risk_cap_percent,
            daily_trades_count=excluded.daily_trades_count,
            daily_loss_percent=excluded.daily_loss_percent,
            max_daily_trades=excluded.max_daily_trades,
            max_daily_loss_percent=excluded.max_daily_loss_percent,
            maximum_instrument_cap_usage=excluded.maximum_instrument_cap_usage,
            instrument_cap_limit=excluded.instrument_cap_limit,
            watchlist_symbols=excluded.watchlist_symbols,
            reason_codes=excluded.reason_codes""", (
                at.isoformat(), "weltrade", trade_mode, settings.emergency_stop.value,
                balance, equity, currency, settings.risk_percent, MAX_RISK_PERCENT,
                daily_count, daily_loss, settings.max_trades_daily,
                settings.max_daily_loss, cap_count,
                settings.max_daily_trades_per_instrument, cap_symbols,
                json.dumps(snapshot.reason_codes),
            ))
    return snapshot


def evaluate(settings: Settings, *, terminal=mt5) -> ExecutionSafetySnapshot:
    """Read broker facts and publish a non-authorizing safety observation."""
    at = datetime.now(timezone.utc)
    reasons: list[str] = []
    trade_mode = None
    balance = equity = None
    currency = account_id = None
    daily_count = daily_loss = cap_count = cap_symbols = None
    authority = DailyStateAuthority.NOT_AUTHORITATIVE
    unresolved = 0
    connected = False

    enforce_weltrade_only(broker=settings.effective_broker, market_data_source=settings.market_data_source)
    path = settings.weltrade_terminal_path
    login = settings.effective_weltrade_login
    server = settings.effective_weltrade_server
    password = settings.effective_weltrade_password
    if path is None or not Path(path).is_file() or login is None or not server or not password:
        reasons.append("WELTRADE_DEMO_CONFIGURATION_INCOMPLETE")
    else:
        try:
            connected = terminal.initialize(str(Path(path).resolve())) is True
            if not connected or terminal.login(login, password=password, server=server) is not True:
                reasons.append("WELTRADE_CONNECTION_UNAVAILABLE")
            else:
                raw = terminal.account_info()
                info = terminal.terminal_info()
                if raw is None or info is None or getattr(info, "connected", False) is not True:
                    reasons.append("WELTRADE_CONNECTION_UNAVAILABLE")
                elif (getattr(raw, "server", None) != server
                      or "WELTRADE" not in str(raw.server).upper()
                      or getattr(raw, "login", None) != login
                      or Path(str(getattr(info, "path", ""))).resolve() != Path(path).resolve().parent):
                    reasons.append("WELTRADE_IDENTITY_MISMATCH")
                else:
                    trade_mode = getattr(raw, "trade_mode", None)
                    DemoOnlyGuard.assert_demo_account("weltrade", raw)
                    account_id = str(raw.login)
                    balance = float(raw.balance)
                    equity = float(raw.equity)
                    currency = str(raw.currency)
                    if (getattr(info, "trade_allowed", False) is not True
                            or getattr(info, "tradeapi_disabled", True) is True):
                        reasons.append("TERMINAL_TRADING_DISABLED")
                    if not all(math.isfinite(value) and value > 0 for value in (balance, equity)):
                        reasons.append("CAPITAL_UNAVAILABLE")
                    day_start = datetime.combine(at.date(), time.min, tzinfo=timezone.utc)
                    history = read_mt5_trade_history_snapshot(
                        terminal, start=day_start, end=at, count=500, connected=True,
                    )
                    if not history.covers(day_start, at):
                        reasons.append("DAILY_HISTORY_UNAVAILABLE")
                    elif balance is not None and balance > 0:
                        risk = RiskEngine(
                            max_daily_loss=settings.max_daily_loss,
                            max_trades_daily=settings.max_trades_daily,
                        )
                        risk.reconcile_daily_history(history.trades, balance)
                        state = risk.get_daily_state()
                        daily_count = state.daily_trades_count
                        daily_loss = state.daily_realized_loss_percent
                        authority = DailyStateAuthority.AUTHORITATIVE
                        limits_ok, _ = risk.evaluate_limits()
                        if not limits_ok:
                            reasons.append("DAILY_RISK_LIMIT_REACHED")
                    positions = terminal.positions_get()
                    if positions is None:
                        reasons.append("POSITIONS_UNAVAILABLE")
                    elif len(positions) >= demo_position_cap(settings, equity=equity, currency=currency):
                        reasons.append("OPEN_POSITION_LIMIT_REACHED")
                    try:
                        cap_clear, cap_count, cap_symbols = _daily_cap_state(settings, account_id, at)
                        if not cap_clear:
                            reasons.append("DAILY_INSTRUMENT_CAP_REACHED")
                    except (OSError, sqlite3.Error, ValueError):
                        reasons.append("DAILY_INSTRUMENT_CAP_UNAVAILABLE")
                    try:
                        unresolved = _unresolved_count(settings)
                        if unresolved:
                            reasons.append("UNRESOLVED_DURABLE_INTENT")
                    except (OSError, sqlite3.Error, ValueError):
                        reasons.append("DURABLE_INTENT_STATE_UNAVAILABLE")
        except Exception as exc:
            # Never report an unreadable broker state as authorization.
            reasons.append(type(exc).__name__.upper())
        finally:
            if connected:
                terminal.shutdown()

    if settings.emergency_stop is not EmergencyStopState.CLEAR:
        reasons.append("EMERGENCY_STOP_NOT_CLEAR")
    if settings.risk_percent <= 0 or not math.isfinite(settings.risk_percent):
        reasons.append("CONFIGURED_RISK_INVALID")
    if balance is not None and balance > 0 and balance * MAX_RISK_PERCENT / 100 <= 0:
        reasons.append("RISK_CAPITAL_UNAVAILABLE")
    if authority is not DailyStateAuthority.AUTHORITATIVE:
        reasons.append("DAILY_STATE_NOT_AUTHORITATIVE")
    return _publish_evidence(
        settings, at=datetime.now(timezone.utc), trade_mode=trade_mode,
        balance=balance, equity=equity, currency=currency,
        daily_count=daily_count, daily_loss=daily_loss,
        cap_count=cap_count, cap_symbols=cap_symbols,
        reasons=reasons, authority=authority, unresolved=unresolved,
        account_id=account_id,
    )


def main() -> None:
    snapshot = evaluate(Settings())
    print(json.dumps({
        "observed_at": snapshot.observed_at.isoformat(),
        "broker": snapshot.broker,
        "authorization": snapshot.execution_authorization.value,
        "daily_state_authority": snapshot.daily_state_authority.value,
        "reason_codes": snapshot.reason_codes,
    }))


if __name__ == "__main__":
    main()
