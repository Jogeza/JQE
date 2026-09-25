"""Explicitly opted-in continuous paper runtime command."""

from __future__ import annotations

import argparse
import asyncio
import signal as process_signal
from time import perf_counter
from datetime import datetime, timedelta, timezone

import pandas as pd

from broker.types import ClosedMarketObservation, ExecutionQuantityUnit, OrderSide, Timeframe, TIMEFRAME_SECONDS
from broker.deriv_public_data import DerivPublicMarketData
from broker.mt5_demo import MT5DemoGateway
from broker.mt5_telemetry import VerifiedDemoMT5Telemetry
from broker.simulation_gateway import SimulationGateway
from config import settings
from core.data_validator import validate_market_data
from core.exceptions import BrokerConnectionError, MarketDataError
from core.indicators import calculate_indicators
from core.regime import detect_regime
from data.market_observation import closed_observations_from_candles, provider_symbol_for
from execution.idempotency import build_execution_idempotency_key
from execution.paper_runtime import ContinuousPaperRuntime, PaperEntry, PaperRuntimeStateStore
from execution.persistence import SQLiteIntentRecordStore
from execution.policy import ExecutionContext, ExecutionIntent
from intelligence.trade_plan import TradePlanBuilder
from notifications.events import JQENotificationEvents
from notifications.factory import notification_service_from_settings
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


class SimulationObservationSource:
    """Fresh synthetic candles from the supported network-free simulation gateway."""

    label = "simulation"

    def __init__(self) -> None:
        self.gateway = SimulationGateway(starting_balance=settings.account_balance)
        self.connected = False

    async def __call__(self) -> list[ClosedMarketObservation]:
        if not self.connected:
            await self.gateway.connect()
            self.connected = True
        timeframe = Timeframe(settings.default_timeframe.upper())
        step = TIMEFRAME_SECONDS[timeframe]
        now = datetime.now(timezone.utc)
        anchor = datetime.fromtimestamp(int(now.timestamp()) // step * step, tz=timezone.utc)
        candles = await self.gateway.get_candles(
            settings.default_symbol, timeframe, settings.default_candle_count, end=anchor
        )
        return closed_observations_from_candles(
            candles=candles, canonical_symbol=settings.default_symbol,
            provider_symbol=settings.default_symbol, source="simulation",
            timeframe=timeframe,
        )

    async def close(self) -> None:
        if self.connected:
            await self.gateway.disconnect()
            self.connected = False


def _assert_fresh(observations: list[ClosedMarketObservation], timeframe: Timeframe) -> None:
    """Reject closed candles whose proven close is too far in the past."""
    now = datetime.now(timezone.utc)
    maximum_age = timedelta(seconds=3 * TIMEFRAME_SECONDS[timeframe])
    if now - observations[-1].closed_at > maximum_age:
        raise MarketDataError(
            "provider closed candles are stale",
            symbol=observations[-1].canonical_symbol,
            closed_at=observations[-1].closed_at.isoformat(),
        )


class DerivPublicObservationSource:
    """Closed candles from the unauthenticated public Deriv feed."""

    label = "deriv_public"

    def __init__(self) -> None:
        self.source = DerivPublicMarketData(
            app_id=settings.deriv_app_id, endpoint=settings.deriv_public_endpoint
        )
        self.connected = False

    async def __call__(self) -> list[ClosedMarketObservation]:
        if not self.connected:
            await self.source.connect()
            self.connected = True
        timeframe = Timeframe(settings.default_timeframe.upper())
        provider_symbol = provider_symbol_for(
            canonical_symbol=settings.default_symbol, source=self.label
        )
        try:
            candles = await self.source.get_candles(
                provider_symbol, timeframe, settings.default_candle_count
            )
        except BrokerConnectionError:
            self.connected = False
            raise
        observations = closed_observations_from_candles(
            candles=candles, canonical_symbol=settings.default_symbol,
            provider_symbol=provider_symbol, source=self.label, timeframe=timeframe,
        )
        _assert_fresh(observations, timeframe)
        return observations

    async def close(self) -> None:
        if self.connected:
            await self.source.disconnect()
            self.connected = False


class WeltradeDemoObservationSource:
    """Closed candles from the already-logged-in Weltrade demo terminal.

    Read-only by construction: the gateway is built without credentials, so
    ``mt5.login`` is never invoked and the terminal session shared with the
    PainX forward collector cannot be detached or re-authenticated.  Identity
    is verified against the configured demo login after attach; any mismatch
    fails closed.
    """

    label = "weltrade_demo"

    def __init__(self) -> None:
        if settings.weltrade_terminal_path is None:
            raise MarketDataError("Weltrade demo data requires a configured terminal path")
        if settings.effective_weltrade_login is None:
            raise MarketDataError("Weltrade demo data requires a configured demo login")
        self.telemetry = VerifiedDemoMT5Telemetry(MT5DemoGateway(
            terminal_path=settings.weltrade_terminal_path,
            login=None, password=None, server=None,
            expected_environment="demo",
            strict_lifecycle=settings.environment == "production",
        ))
        self.connected = False

    async def _attach(self) -> None:
        await self.telemetry.connect()
        account = await self.telemetry.get_account_info()
        if (account.trade_mode or "").lower() != "demo":
            await self.telemetry.disconnect()
            raise BrokerConnectionError("Weltrade observation source requires a demo account")
        if int(account.account_id) != int(settings.effective_weltrade_login):
            await self.telemetry.disconnect()
            raise BrokerConnectionError(
                "Weltrade terminal account does not match the configured demo login"
            )
        self.connected = True

    async def __call__(self) -> list[ClosedMarketObservation]:
        if not self.connected:
            await self._attach()
        timeframe = Timeframe(settings.default_timeframe.upper())
        try:
            candles = await self.telemetry.get_candles(
                settings.default_symbol, timeframe, settings.default_candle_count
            )
        except BrokerConnectionError:
            self.connected = False
            raise
        observations = closed_observations_from_candles(
            candles=candles, canonical_symbol=settings.default_symbol,
            provider_symbol=settings.default_symbol, source=self.label,
            timeframe=timeframe,
        )
        _assert_fresh(observations, timeframe)
        return observations

    async def close(self) -> None:
        if self.connected:
            await self.telemetry.disconnect()
            self.connected = False


def build_observation_source(choice: str | None) -> object:
    """Resolve the opted-in observation source; synthetic stays available."""
    selected = (choice or settings.market_data_source).strip().lower()
    if selected == "simulation":
        return SimulationObservationSource()
    if selected == "deriv_public":
        return DerivPublicObservationSource()
    if selected == "broker":
        return WeltradeDemoObservationSource()
    raise ValueError(f"unsupported paper runtime market data source: {selected!r}")


async def evaluate_production_decision(
    observations: list[ClosedMarketObservation],
    *, execution_context: ExecutionContext | None = None,
    signal_override: dict[str, object] | None = None,
    entry_price: float | None = None,
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
    signal = signal_override or generate_trading_signal(frame, settings.default_symbol, regime=regime)
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
    effective_entry = float(latest["close"]) if entry_price is None else float(entry_price)
    plan = TradePlanBuilder(atr_sl_multiplier=2.0, target_rr=2.0).build(
        symbol=settings.default_symbol, intelligence=intelligence,
        signal_dict=signal, price=effective_entry,
    )
    if not plan.is_valid():
        facts["block_reason"] = "INVALID_TRADE_PLAN"
        return None, facts
    side = OrderSide(plan.signal)
    sizing = authorize_execution_quantity(
        broker="simulation", balance=settings.account_balance,
        risk_percent=risk["risk_percent"], entry=effective_entry,
        stop_loss=plan.stop_loss,
    )
    if sizing.quantity is None or sizing.quantity.unit is not ExecutionQuantityUnit.SIMULATION_UNITS:
        facts["block_reason"] = sizing.reason
        return None, facts
    facts["authorized_quantity"] = sizing.quantity.value
    key = build_execution_idempotency_key(
        symbol=settings.default_symbol, side=side.value, quantity=sizing.quantity,
        entry=effective_entry, stop_loss=plan.stop_loss,
        take_profit=plan.take_profit, signal_time=latest["time"],
    )
    intent = ExecutionIntent(
        symbol=settings.default_symbol, side=side, quantity=sizing.quantity,
        authorized_risk_amount=sizing.authorized_risk_amount,
        expected_loss_at_stop=sizing.expected_loss_at_stop,
        quantity_risk_verified=sizing.risk_verifiable, entry=effective_entry,
        stop_loss=plan.stop_loss, take_profit=plan.take_profit,
        idempotency_key=key, risk_approved=True,
    )
    context = execution_context or ExecutionContext(
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


async def evaluate_strategy_candidate(
    observations: list[ClosedMarketObservation],
) -> tuple[dict[str, object], dict[str, object]]:
    """Evaluate only the canonical strategy through the current closed candle."""
    frame = pd.DataFrame([{
        "time": item.candle_opened_at, "open": item.open, "high": item.high,
        "low": item.low, "close": item.close, "volume": item.volume, "source": item.source,
    } for item in observations])
    if not validate_market_data(frame):
        raise ValueError("paper runtime market data failed validation")
    frame = calculate_indicators(frame)
    regime = detect_regime(frame)
    started = perf_counter()
    signal = generate_trading_signal(
        frame, settings.default_symbol, regime=regime, include_details=True
    )
    intelligence = dict(signal.get("intelligence", {}))
    return signal, {
        "regime": str(regime),
        "signal_direction": str(signal.get("signal", "NO_TRADE")),
        "signal_confidence": signal.get("confidence"),
        "confirmation_state": "NOT_EVALUATED",
        "risk_authorization_state": "NOT_EVALUATED",
        "momentum": intelligence.get("momentum", intelligence.get("momentum_state")),
        "volatility": intelligence.get("volatility", intelligence.get("volatility_state")),
        "rsi": intelligence.get("rsi"),
        "strategy_duration_ms": (perf_counter() - started) * 1000,
    }


async def _production_decision(observations: list[ClosedMarketObservation]) -> PaperEntry | None:
    decision, _ = await evaluate_production_decision(observations)
    return decision


async def run(*, once: bool, source: str | None = None) -> int:
    if settings.broker_execution_enabled:
        raise RuntimeError("paper runtime requires broker execution disabled")
    observation_source = build_observation_source(source)
    source_label = getattr(observation_source, "label", "simulation")
    runtime = ContinuousPaperRuntime(
        observation_source=observation_source, decision_builder=_production_decision,
        intent_records=SQLiteIntentRecordStore(settings.paper_runtime_intent_store_path),
        state_store=PaperRuntimeStateStore(settings.paper_runtime_state_path),
        symbols=(settings.default_symbol,), enabled=settings.paper_runtime_enabled,
        runtime_mode=settings.runtime_mode, poll_seconds=settings.paper_runtime_poll_seconds,
        max_backoff_seconds=settings.paper_runtime_max_backoff_seconds,
        notifications=JQENotificationEvents(notification_service_from_settings(settings)),
        market_data_source=source_label,
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
    finally:
        await observation_source.close()
    print(f"RUNTIME_MODE={heartbeat.runtime_mode.upper()}")
    print(f"CYCLES_COMPLETED={heartbeat.cycles_completed}")
    print(f"LAST_ACTION={heartbeat.last_action}")
    print(f"LAST_ERROR={heartbeat.last_error or 'NONE'}")
    print("BROKER_EXECUTION=DISABLED")
    print(f"MARKET_DATA_SOURCE={heartbeat.market_data_source.upper()}")
    return 0 if heartbeat.last_error is None else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument(
        "--source", choices=("simulation", "deriv_public", "broker"), default=None,
        help="read-only candle source; defaults to JQE_MARKET_DATA_SOURCE",
    )
    args = parser.parse_args()
    return asyncio.run(run(once=args.once, source=args.source))


if __name__ == "__main__":
    raise SystemExit(main())
