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
from dataclasses import dataclass, replace
from datetime import datetime, time, timezone

import pandas as pd

from broker.factory import get_gateway
from broker.simulation_gateway import ObservedSimulationExecutionGateway
from broker.types import AccountIdentity, AccountInfo, OrderSide, Timeframe
from config import EmergencyStopState, settings
from core.data_validator import validate_market_data
from core.exceptions import ConfigurationError, ExecutionError, JQEError, MarketDataError
from core.indicators import calculate_indicators
from core.logger import logger
from core.regime import detect_regime
from data.market_observation import (
    closed_observations_from_candles,
    provider_symbol_for,
    resolved_market_source,
)
from intelligence.trade_plan import TradePlanBuilder
from execution.executor import AsyncTradeExecutor, ReconciliationState
from execution.idempotency import build_execution_idempotency_key
from execution.persistence import SQLiteIntentRecordStore, SQLitePositionLedger
from execution.daily_instrument_guard import DailyInstrumentCapReached, DailyInstrumentTradeGuard
from execution.policy import ExecutionContext, ExecutionIntent
from execution.reconciliation import get_reconciliation_adapter
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
    RiskDecisionCode,
    approve_trade,
    get_reconciled_daily_state,
    reconcile_daily_history,
)
from risk.position_sizing import ExecutionSizingDecision, authorize_execution_quantity
from strategy.pipeline import generate_trading_signal
from notifications.events import JQENotificationEvents
from notifications.factory import notification_service_from_settings

_TIMEFRAME_BY_NAME: dict[str, Timeframe] = {tf.value: tf for tf in Timeframe}
_SIDE_BY_SIGNAL: dict[str, OrderSide] = {"BUY": OrderSide.BUY, "SELL": OrderSide.SELL}


@dataclass(frozen=True, slots=True)
class ExecutionComposition:
    """Broker-aware durable execution dependencies resolved once per startup."""

    account: AccountInfo
    identity: AccountIdentity
    records: SQLiteIntentRecordStore
    position_ledger: SQLitePositionLedger
    reconciler: object
    daily_instrument_guard: DailyInstrumentTradeGuard


async def build_execution_composition(gateway, *, broker: str, active_settings=settings) -> ExecutionComposition:
    account = await gateway.get_account_info()
    normalized_broker = broker.strip().lower()
    trade_mode = account.trade_mode or ("simulation" if normalized_broker == "simulation" else "unknown")
    identity = AccountIdentity(
        broker=normalized_broker,
        account_id=account.account_id,
        server=account.server,
        currency=account.currency,
        trade_mode=trade_mode,
    )
    if normalized_broker in {"mt5", "mt5_demo", "weltrade", "weltrade_demo"}:
        if identity.account_id.strip().upper() == "SIMULATED":
            raise ConfigurationError("MT5-based startup resolved the legacy SIMULATED account sentinel")
        if identity.trade_mode != "demo":
            raise ConfigurationError("MT5-based startup account identity is not authoritatively DEMO")
    position_ledger = SQLitePositionLedger(active_settings.execution_position_ledger_path)
    daily_instrument_guard = DailyInstrumentTradeGuard(
        active_settings.daily_instrument_trade_store_path,
        limit=active_settings.max_daily_trades_per_instrument,
    )
    records = SQLiteIntentRecordStore(active_settings.intent_store_path)
    reconciler = get_reconciliation_adapter(
        broker=normalized_broker, gateway=gateway, ledger=position_ledger
    )
    return ExecutionComposition(account, identity, records, position_ledger, reconciler, daily_instrument_guard)


async def authorize_broker_execution_quantity(
    gateway, *, broker: str, symbol: str, side: OrderSide, balance: float,
    risk_percent: float, entry: float, stop_loss: float,
) -> ExecutionSizingDecision:
    """Use the gateway's authoritative MT5 P/L and margin model when applicable."""
    if broker.strip().lower() in {"mt5", "mt5_demo", "weltrade", "weltrade_demo"}:
        quantity, facts = await gateway.authorize_account_currency_risk(
            symbol=symbol, side=side, balance=balance,
            risk_percent=risk_percent, entry=entry, stop_loss=stop_loss,
        )
        return ExecutionSizingDecision(
            authorized_risk_amount=float(facts["authorized_risk_amount"]),
            quantity=quantity,
            expected_loss_at_stop=float(facts["expected_loss_at_stop"]),
            risk_verifiable=True,
            reason="MT5 quantity verified by broker order_calc_profit/order_calc_margin",
        )
    return authorize_execution_quantity(
        broker=broker, balance=balance, risk_percent=risk_percent,
        entry=entry, stop_loss=stop_loss,
    )


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
    notification_events = JQENotificationEvents(notification_service_from_settings(settings))

    if settings.broker not in ("simulation", "deriv", "deriv_demo", "mt5", "mt5_demo"):
        raise ConfigurationError(f"Unsupported broker: {settings.broker}")
    if (
        settings.broker in ("deriv", "deriv_demo")
        and not settings.broker_execution_enabled
    ):
        raise ConfigurationError("Application execution is authorized for simulation only")

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
        limits_available = all(
            value is not None
            for value in (daily_loss, daily_count, max_daily_loss, max_daily_trades)
        )
        limits_clear = bool(
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

    publish_risk(
        RiskEvaluationState.NOT_EVALUATED,
        "Durable risk evaluation has not completed",
    )
    publish_safety(ExecutionAuthorization.NOT_EVALUATED, ("NOT_EVALUATED",))

    timeframe = _TIMEFRAME_BY_NAME.get(settings.default_timeframe, Timeframe.H1)

    gateway = get_gateway(settings)

    async with gateway:
        composition = await build_execution_composition(
            gateway, broker=settings.broker, active_settings=settings
        )
        account_identity = composition.identity
        records = composition.records
        reconciler = composition.reconciler
        recovery = await StartupRecoveryService(
            records,
            reconciler,
            broker=settings.broker,
            account_id=account_identity.account_id,
        ).recover()
        unresolved_records = records.list_unresolved()
        if unresolved_records:
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

        # Market acquisition is deliberately independent of the execution
        # gateway.  This prevents a simulation fill price from silently
        # becoming the input to strategy/risk evaluation.
        provider_symbol = provider_symbol_for(
            canonical_symbol=settings.default_symbol,
            source=settings.market_data_source,
        )
        async with resolved_market_source(settings) as (market_source, source_name):
            candles = await market_source.get_candles(
                symbol=provider_symbol,
                timeframe=timeframe,
                # Ask for one extra candle because the provider's latest
                # interval can still be forming and must be excluded.
                count=settings.default_candle_count + 1,
            )
        observations = closed_observations_from_candles(
            candles=candles,
            canonical_symbol=settings.default_symbol,
            provider_symbol=provider_symbol,
            source=source_name,
            timeframe=timeframe,
        )
        if len(observations) < settings.default_candle_count:
            raise MarketDataError(
                "Insufficient provably closed market candles",
                symbol=settings.default_symbol,
            )
        observations = observations[-settings.default_candle_count :]
        market_observation = observations[-1]
        df = pd.DataFrame(
            [
                {
                    "time": observation.candle_opened_at,
                    "open": observation.open,
                    "high": observation.high,
                    "low": observation.low,
                    "close": observation.close,
                    "volume": observation.volume,
                    "source": observation.source,
                }
                for observation in observations
            ]
        )

        if not validate_market_data(df):
            raise MarketDataError("Market data failed validation", symbol=settings.default_symbol)

        df = calculate_indicators(df)
        regime = detect_regime(df)
        signal = generate_trading_signal(df, settings.default_symbol, regime=regime)

        logger.info("Market regime: {}", regime)
        logger.info("Trading signal: {}", signal)

        account = composition.account
        history_end = datetime.now(timezone.utc)
        history_start = datetime.combine(history_end.date(), time.min, tzinfo=timezone.utc)
        history = await gateway.get_trade_history_snapshot(
            start=history_start,
            end=history_end,
            count=500,
        )
        trades = history.trades
        history_authoritative = history.covers(history_start, history_end)
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
            publish_risk(
                RiskEvaluationState.BLOCKED,
                risk_decision["reason"],
                account=account,
                daily_loss=daily_loss,
                daily_count=daily_count,
                max_daily_loss=max_daily_loss,
                max_daily_trades=max_daily_trades,
            )
            reason_code = risk_decision.get("reason_code")
            if not reason_code:
                reason_str = str(risk_decision.get("reason", "")).strip().lower()
                if "no trade" in reason_str:
                    reason_code = RiskDecisionCode.NO_TRADE_SIGNAL.value
                elif "confidence" in reason_str:
                    reason_code = RiskDecisionCode.CONFIDENCE_TOO_LOW.value
                elif "trade limit" in reason_str or "daily trade" in reason_str:
                    reason_code = RiskDecisionCode.DAILY_TRADE_LIMIT_REACHED.value
                elif "loss limit" in reason_str or "daily loss" in reason_str:
                    reason_code = RiskDecisionCode.DAILY_LOSS_LIMIT_REACHED.value
                elif "volatility" in reason_str:
                    reason_code = RiskDecisionCode.LOW_VOLATILITY.value
                elif "spread" in reason_str:
                    reason_code = RiskDecisionCode.SPREAD_TOO_HIGH.value
                elif "market data" in reason_str:
                    reason_code = RiskDecisionCode.INVALID_MARKET_DATA.value
                elif "missing signal" in reason_str:
                    reason_code = RiskDecisionCode.MISSING_SIGNAL.value
                else:
                    reason_code = "RISK_REJECTED"
            await notification_events.trade_rejected(
                reason=str(reason_code),
                facts={"Details": str(risk_decision["reason"])},
            )
            logger.info("Cycle complete — no order submitted ({})", risk_decision["reason"])
            return

        latest = df.iloc[-1]
        if (
            plan_symbol := signal.get("symbol", settings.default_symbol)
        ) and str(plan_symbol).strip().upper() != market_observation.canonical_symbol:
            raise ExecutionError("Signal symbol does not match the market observation")
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
            await notification_events.trade_rejected(
                reason="MISSING_OR_INVALID_STOP_LOSS_TAKE_PROFIT",
                facts={"Symbol": settings.default_symbol},
            )
            logger.info(
                "Cycle complete — Trade plan invalid: {}",
                ", ".join(plan.warnings) if plan.warnings else plan.invalidation,
            )
            return

        side = _SIDE_BY_SIGNAL[plan.signal]
        sizing = await authorize_broker_execution_quantity(
            gateway,
            broker=settings.broker,
            symbol=plan.symbol,
            side=side,
            balance=account.balance,
            risk_percent=risk_decision["risk_percent"],
            entry=float(latest["close"]),
            stop_loss=plan.stop_loss,
        )
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

        normalized_symbol = plan.symbol.strip().upper()
        if normalized_symbol != market_observation.canonical_symbol:
            raise ExecutionError("Trade plan symbol does not match the market observation")
        idempotency_key = build_execution_idempotency_key(
            symbol=normalized_symbol,
            side=side.value,
            quantity=sizing.quantity,
            entry=float(latest["close"]),
            stop_loss=plan.stop_loss,
            take_profit=plan.take_profit,
            signal_time=latest.get("time", df.index[-1]),
        )
        existing_record = records.get(idempotency_key)
        open_positions = PositionSnapshotAdapter.from_positions(
            tuple(await gateway.get_positions())
        )
        execution_environment = settings.environment
        approved_account = account_identity.account_id
        approved_symbols = frozenset({normalized_symbol})
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
            execution_enabled=(
                settings.broker == "simulation" or settings.broker_execution_enabled
            ),
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
        execution_gateway = (
            ObservedSimulationExecutionGateway(gateway, market_observation)
            if settings.broker == "simulation"
            else gateway
        )
        executor = AsyncTradeExecutor(
            execution_gateway,
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
            composition.daily_instrument_guard.consume(
                account_identity.scope,
                intent.symbol,
            )
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

        try:
            result = await executor.submit(
                intent,
                context,
                before_submit=publish_submission_started,
                context_provider=refresh_execution_context,
                after_submit=publish_submission_result,
            )
        except DailyInstrumentCapReached as exc:
            usage = composition.daily_instrument_guard.usage(
                account_identity.scope,
                intent.symbol,
            )
            publish_safety(
                ExecutionAuthorization.BLOCKED,
                (exc.reason_code,),
                daily_authority=DailyStateAuthority.AUTHORITATIVE,
            )
            await notification_events.trade_rejected(
                reason=exc.reason_code,
                facts={
                    "Instrument": usage.instrument,
                    "Submission starts": f"{usage.count}/{usage.limit}",
                    "Reset": f"{usage.reset_at.isoformat()} UTC",
                },
            )
            logger.warning(
                "{} instrument={} usage={}/{} reset_at={}",
                exc.reason_code, usage.instrument, usage.count, usage.limit, usage.reset_at,
            )
            return
        if not terminal_safety_published:
            publish_submission_result(result)
        if not result.decision.allowed:
            await notification_events.trade_rejected(
                reason=result.decision.code.value, facts={"Symbol": intent.symbol}
            )
        elif result.state is ReconciliationState.REJECTED:
            await notification_events.trade_rejected(
                reason="BROKER_REJECTED", facts={"Symbol": intent.symbol}
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
