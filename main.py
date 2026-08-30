"""JQE Trading Engine — main entry point.

Runs one full JQE cycle against the configured broker:

    BrokerGateway connect -> candles -> validation -> indicators ->
    regime detection -> signal generation -> risk evaluation ->
    (if approved) order submission

The broker is fully interchangeable — this module depends only on
:class:`broker.base.BrokerGateway`, selected at runtime by
``config.settings.broker`` (``simulation`` by default, so this runs
out of the box with no credentials). See docs/architecture.md, "Broker
layer".

Run directly to execute a single cycle:

    $ python main.py
"""

from __future__ import annotations

import asyncio
from datetime import datetime, time, timezone

import pandas as pd

from broker.factory import get_gateway
from broker.types import OrderRequest, OrderSide, Timeframe
from config import EmergencyStopState, settings
from core.data_validator import validate_market_data
from core.exceptions import ConfigurationError, ExecutionError, JQEError, MarketDataError
from core.indicators import calculate_indicators
from core.logger import logger
from core.regime import detect_regime
from intelligence.trade_plan import TradePlanBuilder
from execution.executor import AsyncTradeExecutor, ReconciliationState
from execution.idempotency import build_execution_idempotency_key
from execution.persistence import SQLiteIntentRecordStore
from execution.policy import ExecutionContext, ExecutionIntent
from execution.reconciliation import DerivReconciliationAdapter, SimulationReconciliationAdapter
from execution.safety import (
    DailyStateAuthority,
    EmergencyStopState,
    ExecutionAuthorization,
    ExecutionMode,
    ExecutionSafetySnapshot,
    SQLiteExecutionSafetyStore,
    utc_now,
)
from execution.trade_manager import PositionSnapshotAdapter
from risk.risk_controller import (
    approve_trade,
    get_reconciled_daily_state,
    reconcile_daily_history,
)
from strategy.pipeline import generate_trading_signal

_TIMEFRAME_BY_NAME: dict[str, Timeframe] = {tf.value: tf for tf in Timeframe}
_SIDE_BY_SIGNAL: dict[str, OrderSide] = {"BUY": OrderSide.BUY, "SELL": OrderSide.SELL}


async def run() -> None:
    """Runs a single JQE analysis-and-trade cycle end to end.

    Connects to the configured broker, retrieves and validates recent
    candles, computes indicators and regime, generates a trading
    signal, evaluates it through the risk engine, and — if approved —
    submits an order through the broker gateway. The broker connection
    is always closed on the way out (via the gateway's async context
    manager), whether the cycle succeeds or fails.

    Raises:
        core.exceptions.BrokerConnectionError: If the broker connection
            cannot be established.
        core.exceptions.MarketDataError: If market data cannot be
            retrieved or fails validation.
    """
    logger.info(
        "JQE engine online (environment={}, broker={})", settings.environment, settings.broker
    )

    if not settings.use_durable_executor and settings.broker != "simulation":
        raise ConfigurationError("Direct execution is authorized for simulation only")

    safety_store = None
    if settings.use_durable_executor:
        if settings.broker == "simulation":
            pass
        elif settings.broker == "deriv":
            approved_symbols = frozenset(
                symbol.strip().upper()
                for symbol in settings.deriv_approved_symbols
                if isinstance(symbol, str) and symbol.strip()
            )
            if settings.environment != "development":
                raise ConfigurationError(
                    "Durable Deriv DEMO execution requires the development environment"
                )
            if settings.deriv_expected_environment != "demo":
                raise ConfigurationError(
                    "Durable Deriv execution requires the explicit demo environment"
                )
            if settings.deriv_demo_execution_enabled is not True:
                raise ConfigurationError("Durable Deriv DEMO execution is not enabled")
            if not settings.deriv_options_account_id or not settings.deriv_options_account_id.strip():
                raise ConfigurationError(
                    "Durable Deriv DEMO execution requires an approved account"
                )
            if settings.default_symbol.strip().upper() not in approved_symbols:
                raise ConfigurationError(
                    "Durable Deriv DEMO execution requires an approved symbol"
                )
        else:
            raise ConfigurationError(
                "Durable execution is authorized for simulation and Deriv DEMO only"
            )

        safety_store = SQLiteExecutionSafetyStore(
            settings.execution_safety_store_path, initialize=True
        )

        def publish_safety(
            authorization: ExecutionAuthorization,
            reason_codes: tuple[str, ...],
            *,
            daily_authority: DailyStateAuthority = DailyStateAuthority.NOT_EVALUATED,
            unresolved_count: int = 0,
        ) -> None:
            safety_store.publish(
                ExecutionSafetySnapshot(
                    observed_at=utc_now(),
                    emergency_stop_state=settings.emergency_stop,
                    execution_mode=ExecutionMode.DURABLE,
                    broker=settings.broker,
                    environment=settings.environment,
                    durable_executor_enabled=True,
                    daily_state_authority=daily_authority,
                    unresolved_intent_count=unresolved_count,
                    unresolved_intent_blocked=unresolved_count > 0,
                    execution_authorization=authorization,
                    reason_codes=reason_codes,
                )
            )

        publish_safety(ExecutionAuthorization.NOT_EVALUATED, ("NOT_EVALUATED",))

    timeframe = _TIMEFRAME_BY_NAME.get(settings.default_timeframe, Timeframe.H1)

    gateway = get_gateway(settings)
    records = None
    reconciler = None
    if settings.use_durable_executor:
        records = SQLiteIntentRecordStore(settings.intent_store_path)
        reconciler = (
            SimulationReconciliationAdapter(gateway)
            if settings.broker == "simulation"
            else DerivReconciliationAdapter(gateway)
        )
        unresolved_records = records.list_unresolved()
        if unresolved_records:
            assert safety_store is not None
            publish_safety(
                ExecutionAuthorization.BLOCKED,
                ("UNRESOLVED_DURABLE_INTENT",),
                unresolved_count=len(unresolved_records),
            )
            raise ExecutionError(
                "New durable execution blocked: unresolved persisted intents "
                "cannot be safely reconstructed from the current schema",
                unresolved_count=len(unresolved_records),
            )

    async with gateway:
        candles = await gateway.get_candles(
            symbol=settings.default_symbol,
            timeframe=timeframe,
            count=settings.default_candle_count,
        )
        if not candles:
            raise MarketDataError("Market data unavailable", symbol=settings.default_symbol)

        df = pd.DataFrame([candle.model_dump() for candle in candles])

        if not validate_market_data(df):
            raise MarketDataError("Market data failed validation", symbol=settings.default_symbol)

        df = calculate_indicators(df)
        regime = detect_regime(df)
        signal = generate_trading_signal(df, settings.default_symbol, regime=regime)

        logger.info("Market regime: {}", regime)
        logger.info("Trading signal: {}", signal)

        account = await gateway.get_account_info()
        history_authoritative = False
        if settings.use_durable_executor:
            history_end = datetime.now(timezone.utc)
            history_start = datetime.combine(history_end.date(), time.min, tzinfo=timezone.utc)
            history = await gateway.get_trade_history_snapshot(
                start=history_start,
                end=history_end,
                count=500,
            )
            trades = history.trades
            history_authoritative = history.covers(history_start, history_end)
        else:
            trades = await gateway.get_trade_history(count=500)
        reconcile_daily_history(trades, balance=account.balance)

        risk_decision = approve_trade(
            {"signal": signal["signal"], "confidence": signal["confidence"]},
            df,
            balance=account.balance,
            enforce_limits=True,
        )
        logger.info("Risk decision: {}", risk_decision)

        if not risk_decision["approved"]:
            logger.info("Cycle complete — no order submitted ({})", risk_decision["reason"])
            return

        latest = df.iloc[-1]
        builder = TradePlanBuilder(atr_sl_multiplier=2.0, target_rr=2.0)

        # Fallback to df for intelligence if missing ATR
        intelligence = signal.get("intelligence", {})
        if "atr" not in intelligence and "ATR" not in intelligence and "ATR_14" not in intelligence:
            intelligence["atr"] = latest.get("ATR", latest.get("ATR_14"))

        plan = builder.build(
            symbol=settings.default_symbol,
            intelligence=intelligence,
            signal_dict=signal,
            price=latest["close"],
            account_balance=account.balance,
            risk_percent=risk_decision["risk_percent"],
        )

        if not plan.is_valid():
            logger.info(
                "Cycle complete — Trade plan invalid: {}",
                ", ".join(plan.warnings) if plan.warnings else plan.invalidation,
            )
            return

        side = _SIDE_BY_SIGNAL[plan.signal]
        if not settings.use_durable_executor:
            order = OrderRequest(
                symbol=plan.symbol,
                side=side,
                volume=plan.position_size,
                stop_loss=plan.stop_loss,
                take_profit=plan.take_profit,
            )
            result = await gateway.submit_order(order)
            logger.info("Order result: {}", result)
            return

        normalized_symbol = plan.symbol.strip().upper()
        idempotency_key = build_execution_idempotency_key(
            symbol=normalized_symbol,
            side=side.value,
            volume=plan.position_size,
            entry=float(latest["close"]),
            stop_loss=plan.stop_loss,
            take_profit=plan.take_profit,
            signal_time=latest.get("time", df.index[-1]),
        )
        assert records is not None
        assert reconciler is not None
        existing_record = records.get(idempotency_key)
        open_positions = PositionSnapshotAdapter.from_positions(
            tuple(await gateway.get_positions())
        )
        daily_loss, daily_count, max_daily_loss, max_daily_trades = (
            get_reconciled_daily_state()
        )
        is_simulation = settings.broker == "simulation"
        execution_environment = settings.environment
        approved_account = (
            "SIMULATED" if is_simulation else settings.deriv_options_account_id.strip()
        )
        approved_symbols = (
            frozenset({normalized_symbol})
            if is_simulation
            else frozenset(
                symbol.strip().upper()
                for symbol in settings.deriv_approved_symbols
                if isinstance(symbol, str) and symbol.strip()
            )
        )
        context = ExecutionContext(
            emergency_stop=(
                False
                if settings.emergency_stop is EmergencyStopState.CLEAR
                else True
                if settings.emergency_stop is EmergencyStopState.ACTIVE
                else None
            ),
            daily_loss_percent=daily_loss,
            max_daily_loss_percent=max_daily_loss,
            daily_trade_count=daily_count,
            max_daily_trades=max_daily_trades,
            open_positions=open_positions,
            max_open_positions=1,
            used_idempotency_keys=(
                frozenset({idempotency_key}) if existing_record is not None else frozenset()
            ),
            execution_enabled=True,
            dry_run=False,
            broker=settings.broker,
            environment=execution_environment,
            account_id=account.account_id,
            approved_brokers=frozenset({settings.broker}),
            approved_environments=frozenset({execution_environment}),
            approved_accounts=frozenset({approved_account}),
            approved_symbols=approved_symbols,
            daily_state_authoritative=history_authoritative,
        )
        intent = ExecutionIntent(
            symbol=normalized_symbol,
            side=side,
            volume=plan.position_size,
            entry=float(latest["close"]),
            stop_loss=plan.stop_loss,
            take_profit=plan.take_profit,
            idempotency_key=idempotency_key,
            risk_approved=risk_decision["approved"],
        )
        executor = AsyncTradeExecutor(
            gateway,
            records,
            reconciler=reconciler,
        )
        if existing_record is not None:
            result = await executor.reconcile(intent)
            logger.info("Recovered order result: {}", result)
            return
        submission_started = False

        def publish_submission_started(_decision) -> None:
            nonlocal submission_started
            publish_safety(
                ExecutionAuthorization.NOT_EVALUATED,
                ("SUBMISSION_IN_PROGRESS",),
                daily_authority=(
                    DailyStateAuthority.AUTHORITATIVE
                    if history_authoritative
                    else DailyStateAuthority.NOT_AUTHORITATIVE
                ),
            )
            submission_started = True

        result = await executor.submit(
            intent,
            context,
            before_submit=publish_submission_started,
        )
        assert safety_store is not None
        daily_authority = (
            DailyStateAuthority.AUTHORITATIVE
            if history_authoritative
            else DailyStateAuthority.NOT_AUTHORITATIVE
        )
        if not result.decision.allowed:
            publish_safety(
                ExecutionAuthorization.BLOCKED,
                (result.decision.code.value,),
                daily_authority=daily_authority,
            )
        elif submission_started:
            if result.state is ReconciliationState.ALREADY_EXECUTED:
                authorization = ExecutionAuthorization.AUTHORIZED
                reason_codes = ("ORDER_ACCEPTED",)
            elif result.state is ReconciliationState.REJECTED:
                authorization = ExecutionAuthorization.BLOCKED
                reason_codes = ("BROKER_REJECTED",)
            else:
                authorization = ExecutionAuthorization.UNKNOWN
                reason_codes = ("SUBMISSION_OUTCOME_UNKNOWN",)
            publish_safety(
                authorization,
                reason_codes,
                daily_authority=daily_authority,
            )
        logger.info("Order result: {}", result)


def main() -> None:
    """CLI entry point. Runs one cycle and logs any platform-level failure.

    Platform errors (:class:`~core.exceptions.JQEError` and subclasses)
    are caught and logged here rather than propagating as an unhandled
    traceback, since this is the outermost boundary of the application.
    Unexpected (non-platform) exceptions are intentionally left to
    propagate.
    """
    try:
        asyncio.run(run())
    except JQEError as exc:
        logger.error("JQE cycle aborted: {}", exc)


if __name__ == "__main__":
    main()
