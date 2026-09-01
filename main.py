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
from dataclasses import replace
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
from execution.recovery import StartupRecoveryService
from execution.safety import (
    DailyStateAuthority,
    EmergencyStopState,
    ExecutionAuthorization,
    ExecutionMode,
    ExecutionSafetySnapshot,
    RiskAuthorizationSnapshot,
    RiskEvaluationState,
    SQLiteExecutionSafetyStore,
    utc_now,
)
from execution.trade_manager import PositionSnapshotAdapter
from risk.risk_controller import (
    approve_trade,
    authorize_execution_quantity,
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
        safety_store = SQLiteExecutionSafetyStore(
            settings.execution_safety_store_path, initialize=True
        )

        def publish_risk(
            evaluation_state: RiskEvaluationState,
            reason: str,
            *,
            account=None,
            daily_loss: float | None = None,
            daily_count: int | None = None,
            max_daily_loss: float | None = None,
            max_daily_trades: int | None = None,
            authorized_risk_amount: float | None = None,
            authorized_risk_percent: float | None = None,
            quantity=None,
            quantity_available: bool = False,
        ) -> None:
            limits_available = (
                daily_loss is not None
                and daily_count is not None
                and max_daily_loss is not None
                and max_daily_trades is not None
            )
            limits_clear = (
                limits_available
                and daily_loss < max_daily_loss
                and daily_count < max_daily_trades
            )
            safety_store.publish_risk(
                RiskAuthorizationSnapshot(
                    observed_at=utc_now(),
                    broker=settings.broker,
                    environment=settings.environment,
                    account_id=None if account is None else account.account_id,
                    evaluation_state=evaluation_state,
                    balance=None if account is None else account.balance,
                    equity=(
                        None
                        if account is None
                        else account.balance if account.equity is None else account.equity
                    ),
                    currency=None if account is None else account.currency,
                    max_daily_loss=max_daily_loss,
                    max_trades_daily=max_daily_trades,
                    daily_trades_count=daily_count,
                    daily_loss_percent=daily_loss,
                    risk_allowed=limits_clear if limits_available else None,
                    risk_message=("Limits OK" if limits_clear else reason),
                    rejection_reason=(
                        "" if evaluation_state is RiskEvaluationState.AUTHORIZED else reason
                    ),
                    authorized_risk_amount=authorized_risk_amount,
                    authorized_risk_percent=authorized_risk_percent,
                    execution_quantity_available=quantity_available,
                    execution_quantity_value=(
                        quantity.value if quantity_available and quantity is not None else None
                    ),
                    execution_quantity_unit=(
                        quantity.unit.value if quantity_available and quantity is not None else None
                    ),
                    execution_quantity_reason=reason,
                )
            )

        publish_risk(
            RiskEvaluationState.NOT_EVALUATED,
            "Durable risk evaluation has not completed",
        )

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
            publish_risk(
                RiskEvaluationState.NOT_EVALUATED,
                "MT5 execution is disabled",
            )
            raise ConfigurationError(
                "Durable execution is authorized for simulation and Deriv DEMO only"
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

    async with gateway:
        if settings.use_durable_executor:
            assert records is not None
            assert reconciler is not None
            recovery_account_id = (
                "SIMULATED"
                if settings.broker == "simulation"
                else settings.deriv_options_account_id.strip()
            )
            recovery = await StartupRecoveryService(
                records,
                reconciler,
                broker=settings.broker,
                account_id=recovery_account_id,
            ).recover()
            unresolved_records = records.list_unresolved()
            if unresolved_records:
                assert safety_store is not None
                publish_safety(
                    ExecutionAuthorization.BLOCKED,
                    ("UNRESOLVED_DURABLE_INTENT",),
                    unresolved_count=len(unresolved_records),
                )
                raise ExecutionError(
                    "New durable execution blocked after startup recovery: "
                    "unresolved persisted intents remain",
                    unresolved_count=len(unresolved_records),
                    recovery_outcomes=tuple(
                        result.outcome.value for result in recovery.results
                    ),
                )

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

        daily_loss, daily_count, max_daily_loss, max_daily_trades = (
            get_reconciled_daily_state()
        )

        if not risk_decision["approved"]:
            if settings.use_durable_executor:
                publish_risk(
                    RiskEvaluationState.BLOCKED,
                    risk_decision["reason"],
                    account=account,
                    daily_loss=daily_loss,
                    daily_count=daily_count,
                    max_daily_loss=max_daily_loss,
                    max_daily_trades=max_daily_trades,
                )
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
        )

        if not plan.is_valid():
            if settings.use_durable_executor:
                publish_risk(
                    RiskEvaluationState.AUTHORIZED,
                    "Executable quantity unavailable: trade plan is incomplete",
                    account=account,
                    daily_loss=daily_loss,
                    daily_count=daily_count,
                    max_daily_loss=max_daily_loss,
                    max_daily_trades=max_daily_trades,
                    authorized_risk_amount=risk_decision["authorized_risk_amount"],
                    authorized_risk_percent=risk_decision["risk_percent"],
                )
            logger.info(
                "Cycle complete — Trade plan invalid: {}",
                ", ".join(plan.warnings) if plan.warnings else plan.invalidation,
            )
            return

        side = _SIDE_BY_SIGNAL[plan.signal]
        sizing = authorize_execution_quantity(
            broker=settings.broker,
            balance=account.balance,
            risk_percent=risk_decision["risk_percent"],
            entry=float(latest["close"]),
            stop_loss=plan.stop_loss,
        )
        if settings.use_durable_executor:
            quantity_available = sizing.quantity is not None and sizing.risk_verifiable
            publish_risk(
                RiskEvaluationState.AUTHORIZED,
                sizing.reason,
                account=account,
                daily_loss=daily_loss,
                daily_count=daily_count,
                max_daily_loss=max_daily_loss,
                max_daily_trades=max_daily_trades,
                authorized_risk_amount=sizing.authorized_risk_amount,
                authorized_risk_percent=risk_decision["risk_percent"],
                quantity=sizing.quantity,
                quantity_available=quantity_available,
            )
        if not settings.use_durable_executor:
            if sizing.quantity is None or not sizing.risk_verifiable:
                raise ExecutionError("Execution quantity risk could not be verified")
            order = OrderRequest(
                symbol=plan.symbol,
                side=side,
                quantity=sizing.quantity,
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
            quantity=sizing.quantity,
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
            quantity=sizing.quantity,
            authorized_risk_amount=sizing.authorized_risk_amount,
            expected_loss_at_stop=sizing.expected_loss_at_stop,
            quantity_risk_verified=sizing.risk_verifiable,
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
            reservation_lease_seconds=settings.execution_reservation_lease_seconds,
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

        async def refresh_execution_context() -> ExecutionContext:
            nonlocal history_authoritative
            refreshed_account = await gateway.get_account_info()
            refreshed_end = datetime.now(timezone.utc)
            refreshed_start = datetime.combine(
                refreshed_end.date(), time.min, tzinfo=timezone.utc
            )
            refreshed_history = await gateway.get_trade_history_snapshot(
                start=refreshed_start,
                end=refreshed_end,
                count=500,
            )
            refreshed_authoritative = refreshed_history.covers(
                refreshed_start, refreshed_end
            )
            history_authoritative = refreshed_authoritative
            reconcile_daily_history(
                refreshed_history.trades,
                balance=refreshed_account.balance,
            )
            (
                refreshed_daily_loss,
                refreshed_daily_count,
                refreshed_max_daily_loss,
                refreshed_max_daily_trades,
            ) = get_reconciled_daily_state()
            return replace(
                context,
                account_id=refreshed_account.account_id,
                daily_loss_percent=refreshed_daily_loss,
                daily_trade_count=refreshed_daily_count,
                max_daily_loss_percent=refreshed_max_daily_loss,
                max_daily_trades=refreshed_max_daily_trades,
                daily_state_authoritative=refreshed_authoritative,
            )

        terminal_safety_published = False

        def publish_submission_result(result) -> None:
            nonlocal terminal_safety_published
            daily_authority = (
                DailyStateAuthority.AUTHORITATIVE
                if history_authoritative
                else DailyStateAuthority.NOT_AUTHORITATIVE
            )
            if not result.decision.allowed:
                authorization = ExecutionAuthorization.BLOCKED
                reason_codes = (result.decision.code.value,)
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
            else:
                return
            publish_safety(
                authorization,
                reason_codes,
                daily_authority=daily_authority,
            )
            terminal_safety_published = True

        result = await executor.submit(
            intent,
            context,
            before_submit=publish_submission_started,
            context_provider=refresh_execution_context,
            after_submit=publish_submission_result,
        )
        if not terminal_safety_published:
            publish_submission_result(result)
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
