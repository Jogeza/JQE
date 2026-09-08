"""Explicitly opted-in continuous paper runtime command."""

from __future__ import annotations

import argparse
import asyncio
import signal as process_signal
from time import perf_counter
from datetime import datetime, timedelta, timezone

import pandas as pd

from broker.types import ClosedMarketObservation, ExecutionQuantityUnit, OrderSide, Timeframe
from config import settings
from core.data_validator import validate_market_data
from core.indicators import calculate_indicators
from core.regime import detect_regime
from execution.idempotency import build_execution_idempotency_key
from execution.paper_runtime import ContinuousPaperRuntime, PaperEntry, PaperRuntimeStateStore
from execution.persistence import SQLiteIntentRecordStore
from execution.policy import ExecutionContext, ExecutionIntent
from intelligence.trade_plan import TradePlanBuilder
from notifications.events import JQENotificationEvents
from notifications.service import NotificationService
from notifications.telegram import telegram_gateway_from_settings
from risk.risk_controller import approve_trade, authorize_execution_quantity
from strategy.pipeline import generate_trading_signal


def _offline_observations(count: int = 510) -> list[ClosedMarketObservation]:
    """Deterministic local fixture; it performs no market or broker I/O."""
    now = datetime.now(timezone.utc)
    anchor = now.replace(minute=(now.minute // 5) * 5, second=0, microsecond=0)
    start = anchor - timedelta(minutes=5 * (count + 10))
    result = []
    price = 100.0
    for index in range(count):
        opened = start + timedelta(minutes=5 * index)
        close = price + (0.02 if index % 3 else -0.01)
        result.append(ClosedMarketObservation(
            canonical_symbol=settings.default_symbol, source="paper_runtime_fixture",
            provider_symbol=settings.default_symbol, timeframe=Timeframe.M5,
            candle_opened_at=opened, closed_at=opened + timedelta(minutes=5),
            open=price, high=max(price, close) + 0.05, low=min(price, close) - 0.05,
            close=close, volume=10.0,
        ))
        price = close
    return result


async def _source() -> list[ClosedMarketObservation]:
    return _offline_observations()


async def evaluate_production_decision(
    observations: list[ClosedMarketObservation],
) -> tuple[PaperEntry | None, dict[str, object]]:
    frame = pd.DataFrame([{
        "time": item.candle_opened_at, "open": item.open, "high": item.high,
        "low": item.low, "close": item.close, "volume": item.volume, "source": item.source,
    } for item in observations])
    if not validate_market_data(frame):
        raise ValueError("paper runtime market data failed validation")
    frame = calculate_indicators(frame)
    regime = detect_regime(frame)
    strategy_started = perf_counter()
    signal = generate_trading_signal(frame, settings.default_symbol, regime=regime)
    facts: dict[str, object] = {
        "regime": str(regime),
        "signal_direction": str(signal.get("signal", "NO_TRADE")),
        "signal_confidence": signal.get("confidence"),
        "confirmation_state": signal.get("confirmation_state", "NOT_EVALUATED"),
        "strategy_duration_ms": (perf_counter() - strategy_started) * 1000,
    }
    risk_started = perf_counter()
    risk = approve_trade(
        {"signal": signal["signal"], "confidence": signal["confidence"]}, frame,
        balance=settings.account_balance, enforce_limits=True,
    )
    facts["risk_duration_ms"] = (perf_counter() - risk_started) * 1000
    if not risk["approved"]:
        facts.update(risk_authorization_state="BLOCKED", block_reason=risk.get("reason"))
        return None, facts
    facts["risk_authorization_state"] = "AUTHORIZED"
    latest = frame.iloc[-1]
    intelligence = dict(signal.get("intelligence", {}))
    intelligence.setdefault("atr", latest.get("ATR", latest.get("ATR_14")))
    plan = TradePlanBuilder(atr_sl_multiplier=2.0, target_rr=2.0).build(
        symbol=settings.default_symbol, intelligence=intelligence,
        signal_dict=signal, price=float(latest["close"]),
    )
    if not plan.is_valid():
        facts["block_reason"] = "INVALID_TRADE_PLAN"
        return None, facts
    side = OrderSide(plan.signal)
    sizing = authorize_execution_quantity(
        broker="simulation", balance=settings.account_balance,
        risk_percent=risk["risk_percent"], entry=float(latest["close"]),
        stop_loss=plan.stop_loss,
    )
    if sizing.quantity is None or sizing.quantity.unit is not ExecutionQuantityUnit.SIMULATION_UNITS:
        facts["block_reason"] = sizing.reason
        return None, facts
    facts["authorized_quantity"] = sizing.quantity.value
    key = build_execution_idempotency_key(
        symbol=settings.default_symbol, side=side.value, quantity=sizing.quantity,
        entry=float(latest["close"]), stop_loss=plan.stop_loss,
        take_profit=plan.take_profit, signal_time=latest["time"],
    )
    intent = ExecutionIntent(
        symbol=settings.default_symbol, side=side, quantity=sizing.quantity,
        authorized_risk_amount=sizing.authorized_risk_amount,
        expected_loss_at_stop=sizing.expected_loss_at_stop,
        quantity_risk_verified=sizing.risk_verifiable, entry=float(latest["close"]),
        stop_loss=plan.stop_loss, take_profit=plan.take_profit,
        idempotency_key=key, risk_approved=True,
    )
    context = ExecutionContext(
        emergency_stop=settings.emergency_stop.value != "CLEAR",
        daily_loss_percent=0.0, max_daily_loss_percent=settings.max_daily_loss,
        daily_trade_count=0, max_daily_trades=settings.max_trades_daily,
        open_positions=(), max_open_positions=1, used_idempotency_keys=frozenset(),
        execution_enabled=True, dry_run=False, broker="simulation",
        environment="paper_continuous", account_id="PAPER",
        approved_brokers=frozenset({"simulation"}),
        approved_environments=frozenset({"paper_continuous"}),
        approved_accounts=frozenset({"PAPER"}),
        approved_symbols=frozenset({settings.default_symbol.upper()}),
        daily_state_authoritative=True,
    )
    return PaperEntry(intent, context), facts


async def _production_decision(observations: list[ClosedMarketObservation]) -> PaperEntry | None:
    decision, _ = await evaluate_production_decision(observations)
    return decision


async def run(*, once: bool) -> int:
    if settings.broker != "simulation":
        raise RuntimeError("paper runtime forbids broker execution configuration")
    runtime = ContinuousPaperRuntime(
        observation_source=_source, decision_builder=_production_decision,
        intent_records=SQLiteIntentRecordStore(settings.intent_store_path),
        state_store=PaperRuntimeStateStore(settings.paper_runtime_state_path),
        symbols=(settings.default_symbol,), enabled=settings.paper_runtime_enabled,
        runtime_mode=settings.runtime_mode, poll_seconds=settings.paper_runtime_poll_seconds,
        max_backoff_seconds=settings.paper_runtime_max_backoff_seconds,
        notifications=JQENotificationEvents(NotificationService(telegram_gateway_from_settings(settings))),
    )
    loop = asyncio.get_running_loop()
    for shutdown_signal in (process_signal.SIGINT, process_signal.SIGTERM):
        try:
            loop.add_signal_handler(shutdown_signal, runtime.request_stop)
        except (NotImplementedError, RuntimeError):
            pass
    try:
        heartbeat = await runtime.run(once=once)
    except KeyboardInterrupt:
        runtime.request_stop()
        return 130
    print(f"RUNTIME_MODE={heartbeat.runtime_mode.upper()}")
    print(f"CYCLES_COMPLETED={heartbeat.cycles_completed}")
    print(f"LAST_ACTION={heartbeat.last_action}")
    print(f"LAST_ERROR={heartbeat.last_error or 'NONE'}")
    print("BROKER_EXECUTION=DISABLED")
    return 0 if heartbeat.last_error is None else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    return asyncio.run(run(once=args.once))


if __name__ == "__main__":
    raise SystemExit(main())
