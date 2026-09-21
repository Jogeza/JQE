"""Opt-in, DEMO-only controlled trade preview and single-order workflow.

The default mode is preview-only and is *structurally* incapable of sending an
order: the broker gateway is wrapped so that ``submit_order`` raises and the
attempt is counted.  Submission requires both the ``JQE_DEMO_TRADE_TEST_ENABLED``
environment gate and the explicit ``--submit-one-demo-order`` flag, and places
at most one demo order per run with no retry.

Only Deriv demo and Weltrade demo are accepted.  Simulation is never used as a
fallback, and ``JQE_BROKER_EXECUTION_ENABLED`` must remain ``false``.

Authorize explicitly before running::

    set JQE_DEMO_TRADE_TEST_ENABLED=1
    D:\\JQE\\venv\\Scripts\\python.exe tools/demo_trade_preview.py --broker weltrade
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, time as day_start, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from broker.base import BrokerGateway
from broker.demo_guard import DemoOnlyGuard
from broker.factory import get_gateway
from broker.types import (
    ExecutionQuantity,
    ExecutionQuantityUnit,
    OrderSide,
    Timeframe,
)
from config.settings import Settings
from core.data_validator import validate_market_data
from core.exceptions import UnsafeBrokerAccountError
from core.indicators import calculate_indicators
from core.regime import detect_regime
from data.broker_selection import normalize_broker_name
from execution.idempotency import build_execution_idempotency_key
from execution.persistence import SQLiteIntentRecordStore, SQLitePositionLedger
from execution.policy import ExecutionContext, ExecutionIntent, ExecutionPolicy
from execution.reconciliation import get_reconciliation_adapter
from execution.safety import EmergencyStopState, SQLiteExecutionSafetyStore, utc_now
from execution.trade_manager import PositionSnapshotAdapter
from intelligence.trade_plan import TradePlanBuilder
from risk.position_sizing import authorize_execution_quantity
from risk.risk_controller import (
    approve_trade,
    get_reconciled_daily_state,
    reconcile_daily_history,
)
from strategy.pipeline import generate_trading_signal
from tools.demo_synthetic_verification import (
    StepResult,
    _closed_candles,
    _discover_deriv_symbols,
    _discover_weltrade_symbols,
    _mask,
)

_AUTHORIZATION_ENV = "JQE_DEMO_TRADE_TEST_ENABLED"
_SUPPORTED_BROKERS = ("deriv", "weltrade")
_MT5_FAMILY = ("weltrade",)
_PREFERRED_SYMBOLS = {"deriv": "1HZ100V", "weltrade": "FX Vol 20"}
_MIN_CLOSED_CANDLES = 60


class _GuardedGateway:
    """Delegates to a broker gateway while counting submission attempts."""

    def __init__(self, inner: BrokerGateway) -> None:
        self._inner = inner
        self.submission_attempts = 0

    @property
    def inner(self) -> BrokerGateway:
        return self._inner

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def __aenter__(self) -> "_GuardedGateway":
        await self._inner.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> bool:
        return bool(await self._inner.__aexit__(exc_type, exc, traceback))


class PreviewOnlyGateway(_GuardedGateway):
    """Gateway wrapper that makes order submission structurally impossible."""

    async def submit_order(self, order: Any) -> Any:
        self.submission_attempts += 1
        raise AssertionError(
            "demo trade preview mode cannot submit an order; "
            "use --submit-one-demo-order with explicit operator approval"
        )


class _SingleSubmissionExecutor:
    """Caps a run at one canonical executor submission; automatic retry is prohibited.

    Order submission itself stays inside ``execution.executor.AsyncTradeExecutor`` so
    this tool never becomes a second execution boundary.
    """

    def __init__(self, executor: Any) -> None:
        self._executor = executor
        self.submissions = 0

    async def submit(self, intent: Any, context: Any) -> Any:
        if self.submissions >= 1:
            raise AssertionError(
                "at most one demo order may be submitted per run; automatic retry is prohibited"
            )
        self.submissions += 1
        return await self._executor.submit(intent, context)


@dataclass
class DemoTradeReport:
    broker: str
    mode: str
    started_at: str
    finished_at: str | None = None
    outcome: str = "NOT_RUN"
    blockers: list[str] = field(default_factory=list)
    steps: list[StepResult] = field(default_factory=list)
    preview: dict[str, Any] = field(default_factory=dict)
    submission: dict[str, Any] | None = None

    def record(self, step: str, outcome: str, **detail: Any) -> None:
        self.steps.append(StepResult(step=step, status=outcome, detail=detail))

    def block(self, step: str, reason: str, **detail: Any) -> None:
        self.blockers.append(reason)
        self.record(step, "BLOCKED", reason=reason, **detail)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _observe_safety(settings: Settings) -> dict[str, Any]:
    """Read the persisted execution-safety snapshot without mutating it."""
    observation: dict[str, Any] = {
        "configured_emergency_stop": settings.emergency_stop.value,
        "freshness_seconds": settings.execution_safety_freshness_seconds,
        "store_path": str(settings.execution_safety_store_path),
    }
    store = SQLiteExecutionSafetyStore(
        settings.execution_safety_store_path, initialize=False
    )
    try:
        snapshot = store.read()
    except Exception as exc:
        observation.update(state="UNAVAILABLE", reason=f"{type(exc).__name__}: {exc}")
        return observation
    if snapshot is None:
        observation.update(state="NOT_OBSERVED")
        return observation
    observed_at = snapshot.observed_at.astimezone(timezone.utc)
    age_seconds = (utc_now() - observed_at).total_seconds()
    observation.update(
        state=(
            "OBSERVED"
            if age_seconds <= settings.execution_safety_freshness_seconds
            else "STALE"
        ),
        age_seconds=round(age_seconds, 1),
        observed_at=observed_at.isoformat(),
        snapshot_emergency_stop=snapshot.emergency_stop_state.value,
        snapshot_broker=snapshot.broker,
        execution_authorization=snapshot.execution_authorization.value,
        reason_codes=list(snapshot.reason_codes),
        unresolved_intent_count=snapshot.unresolved_intent_count,
        unresolved_intent_blocked=snapshot.unresolved_intent_blocked,
        daily_state_authority=snapshot.daily_state_authority.value,
    )
    return observation


def _unresolved_intents(settings: Settings) -> tuple[int | None, str | None]:
    path = Path(settings.intent_store_path)
    if not path.is_file():
        return 0, None
    try:
        unresolved = SQLiteIntentRecordStore(path, initialize=False).list_unresolved()
    except Exception as exc:
        return None, f"Durable intent store is unreadable: {type(exc).__name__}: {exc}"
    if unresolved:
        return len(unresolved), (
            f"{len(unresolved)} unresolved durable execution intent(s) must be resolved first"
        )
    return 0, None


async def _reverify_demo(
    gateway: _GuardedGateway, broker: str, account: Any
) -> dict[str, Any]:
    """Re-run DemoOnlyGuard immediately before any order construction."""
    inner = gateway.inner
    session_id = str(getattr(inner, "session_id", "") or f"{broker}-demo-preview")
    if broker in _MT5_FAMILY:
        import MetaTrader5 as mt5

        info = await asyncio.to_thread(mt5.account_info)
        DemoOnlyGuard.assert_demo_account(broker, info, session_id=session_id)
        return {
            "guard_broker": broker,
            "checked_field": "trade_mode",
            "observed_value": getattr(info, "trade_mode", None),
            "account_id_masked": _mask(str(getattr(info, "login", "") or "")),
            "server": getattr(info, "server", None),
            "verified": True,
        }

    from broker.deriv_auth import DerivIdentityState

    identity = getattr(inner, "account_identity", None)
    state = getattr(inner, "identity_state", None)
    if (
        state is not DerivIdentityState.VERIFIED_DEMO
        or identity is None
        or identity.environment != "demo"
        or not bool(getattr(inner, "_demo_verified", False))
    ):
        raise UnsafeBrokerAccountError(
            "Deriv account identity is not an authoritatively verified DEMO session",
            broker="deriv",
            account_id=getattr(identity, "account_id", None),
        )
    DemoOnlyGuard.assert_demo_account(
        "deriv",
        {
            "is_virtual": 1,
            "loginid": identity.account_id,
            "currency": account.currency,
        },
        session_id=session_id,
    )
    return {
        "guard_broker": "deriv",
        "checked_field": "is_virtual",
        "observed_value": 1,
        "account_id_masked": _mask(identity.account_id),
        "identity_environment": identity.environment,
        "identity_state": getattr(state, "value", None),
        "verified": True,
    }


def _select_symbol(
    report: DemoTradeReport,
    broker: str,
    source: str,
    discovered: list[dict[str, Any]],
    requested: str | None,
) -> str | None:
    """Confirm the symbol against the broker's own discovery result."""
    names = [str(entry["symbol"]) for entry in discovered]
    if requested:
        match = next((name for name in names if name.strip().upper() == requested.strip().upper()), None)
        if match is None:
            report.block(
                "7-symbol-discovery",
                f"Requested symbol {requested!r} was not confirmed by the broker",
                discovery_source=source,
                confirmed_symbols=names,
            )
            return None
        report.record(
            "7-symbol-discovery",
            "PASSED",
            discovery_source=source,
            confirmed_symbol_count=len(names),
            confirmed_symbols=names,
            selected_symbol=match,
            selection_basis="operator request confirmed by broker discovery",
        )
        return match

    preferred = _PREFERRED_SYMBOLS.get(broker, "")
    match = next((name for name in names if name.strip().upper() == preferred.strip().upper()), None)
    basis = "broker-confirmed preferred synthetic index"
    if match is None and names:
        match = names[0]
        basis = "first broker-confirmed synthetic index (preferred symbol unavailable)"
    if match is None:
        report.block(
            "7-symbol-discovery",
            f"{source} returned no synthetic symbols",
            discovery_source=source,
            confirmed_symbols=names,
        )
        return None
    report.record(
        "7-symbol-discovery",
        "PASSED",
        discovery_source=source,
        confirmed_symbol_count=len(names),
        confirmed_symbols=names,
        selected_symbol=match,
        selection_basis=basis,
    )
    return match


def _closed_frame(
    candles: list[Any], timeframe: Timeframe
) -> tuple[pd.DataFrame | None, dict[str, Any]]:
    closed = _closed_candles(candles, timeframe)
    facts: dict[str, Any] = {
        "candles_returned": len(candles),
        "candles_closed": len(closed),
        "first_candle": closed[0].time.isoformat() if closed else None,
        "last_candle": closed[-1].time.isoformat() if closed else None,
    }
    if len(closed) < _MIN_CLOSED_CANDLES:
        facts["status"] = "INSUFFICIENT_CLOSED_CANDLES"
        return None, facts
    frame = pd.DataFrame(
        [
            {
                "time": candle.time,
                "open": candle.open,
                "high": candle.high,
                "low": candle.low,
                "close": candle.close,
                "volume": candle.volume,
            }
            for candle in closed
        ]
    )
    if not validate_market_data(frame):
        facts["status"] = "MARKET_DATA_INVALID"
        return None, facts
    facts["status"] = "OK"
    return calculate_indicators(frame), facts


def _reason_code_value(risk: dict[str, Any]) -> Any:
    code = risk.get("reason_code")
    return code.value if getattr(code, "value", None) is not None else code


async def _weltrade_instrument_spec(gateway: _GuardedGateway, symbol: str) -> dict[str, Any]:
    """Discover contract size, precision, tick size and stop distance from MT5."""
    import MetaTrader5 as mt5

    spec = await gateway.verify_instrument_risk_spec(symbol)
    real_symbol = str(spec["symbol"])
    info = await asyncio.to_thread(mt5.symbol_info, real_symbol)
    if info is None:
        raise ValueError(f"MT5 symbol_info is unavailable for {real_symbol}")
    point = float(spec["point"])
    stops_level = int(getattr(info, "trade_stops_level", 0) or 0)
    return {
        "source": "MetaTrader5 symbol_info + order_calc_margin",
        "symbol": real_symbol,
        "account_currency": spec["account_currency"],
        "contract_size": spec["contract_size"],
        "tick_size": spec["tick_size"],
        "tick_value": spec["tick_value"],
        "point": point,
        "digits": int(getattr(info, "digits", 0) or 0),
        "volume_min": float(getattr(info, "volume_min", 0) or 0),
        "volume_max": float(getattr(info, "volume_max", 0) or 0),
        "volume_step": float(getattr(info, "volume_step", 0) or 0),
        "stops_level_points": stops_level,
        "minimum_stop_distance": round(stops_level * point, 10),
        "minimum_volume_margin": spec["minimum_volume_margin"],
    }


async def _weltrade_quantity(
    gateway: _GuardedGateway,
    spec: dict[str, Any],
    *,
    side: OrderSide,
    entry: float,
    stop_loss: float,
    take_profit: float,
    authorized_risk: float,
) -> tuple[ExecutionQuantity | None, dict[str, Any], str | None]:
    """Size the smallest broker-valid demo lot and prove its stop risk and margin."""
    import MetaTrader5 as mt5

    real_symbol = str(spec["symbol"])
    lots = float(spec["volume_min"])
    step = float(spec["volume_step"])
    facts: dict[str, Any] = {
        "quantity_basis": "broker minimum volume",
        "volume_min": lots,
        "volume_step": step,
        "volume_max": spec["volume_max"],
        "authorized_risk_amount": authorized_risk,
        "minimum_stop_distance": spec["minimum_stop_distance"],
    }
    if lots <= 0 or step <= 0:
        return None, facts, "Broker minimum volume or volume step is not positive"

    stop_distance = abs(entry - stop_loss)
    take_profit_distance = abs(take_profit - entry)
    minimum_distance = float(spec["minimum_stop_distance"])
    facts.update(
        stop_distance=round(stop_distance, 10),
        take_profit_distance=round(take_profit_distance, 10),
    )
    if stop_distance < minimum_distance or take_profit_distance < minimum_distance:
        return None, facts, (
            "Stop-loss or take-profit distance is below the broker minimum stop distance"
        )

    order_type = mt5.ORDER_TYPE_BUY if side is OrderSide.BUY else mt5.ORDER_TYPE_SELL
    profit = await asyncio.to_thread(
        mt5.order_calc_profit, order_type, real_symbol, lots, entry, stop_loss
    )
    if profit is None:
        return None, facts, "Broker could not compute the loss at the configured stop"
    expected_loss = abs(float(profit))
    margin = await asyncio.to_thread(
        mt5.order_calc_margin, order_type, real_symbol, lots, entry
    )
    account = await asyncio.to_thread(mt5.account_info)
    free_margin = float(getattr(account, "margin_free", 0) or 0) if account else 0.0
    facts.update(
        expected_loss_at_stop=round(expected_loss, 6),
        margin_requirement=None if margin is None else round(float(margin), 6),
        free_margin=round(free_margin, 6),
    )
    if expected_loss <= 0:
        return None, facts, "Broker-computed loss at stop is not positive"
    if expected_loss > authorized_risk:
        return None, facts, (
            f"Minimum broker volume risks {expected_loss:.2f}, above the authorized "
            f"risk of {authorized_risk:.2f}"
        )
    if margin is None or float(margin) <= 0 or float(margin) > free_margin:
        return None, facts, "Broker margin requirement is unverifiable or exceeds free margin"

    quantity = ExecutionQuantity(value=round(lots, 8), unit=ExecutionQuantityUnit.MT5_LOTS)
    return quantity, facts, None


async def _deriv_instrument_spec(
    gateway: _GuardedGateway, symbol: str, side: OrderSide, currency: str
) -> dict[str, Any]:
    """Discover Deriv contract capability and a read-only proposal for the symbol."""
    from broker.deriv_demo_proposal import discover_demo_proposal
    from broker.deriv_gateway import _provider_symbol

    provider_symbol = _provider_symbol(symbol)
    contract_type = "MULTUP" if side is OrderSide.BUY else "MULTDOWN"

    class _Transport:
        def __init__(self, inner: BrokerGateway) -> None:
            self._inner = inner

        async def request(self, payload: Any) -> Any:
            return await self._inner._request(payload)  # noqa: SLF001 - broker-scoped tool

    evidence = await discover_demo_proposal(
        _Transport(gateway.inner),
        provider_symbol=provider_symbol,
        currency=currency,
        contract_type=contract_type,
    )
    capability = evidence.capability
    return {
        "source": "Deriv active_symbols + contracts_for + read-only proposal",
        "provider_symbol": capability.provider_symbol,
        "display_name": evidence.symbol.display_name,
        "market": evidence.symbol.market,
        "submarket": evidence.symbol.submarket,
        "exchange_is_open": evidence.symbol.is_open,
        "contract_type": capability.contract_type,
        "quantity_basis": capability.quantity_basis.value if capability.quantity_basis else None,
        "multiplier_values": [str(value) for value in capability.multiplier_values],
        "minimum_quantity": (
            None if capability.minimum_quantity is None else float(capability.minimum_quantity)
        ),
        "maximum_quantity": (
            None if capability.maximum_quantity is None else float(capability.maximum_quantity)
        ),
        "minimum_duration": capability.minimum_duration,
        "maximum_duration": capability.maximum_duration,
        "stop_loss_advertised": capability.stop_loss_advertised,
        "take_profit_advertised": capability.take_profit_advertised,
        "proposal_ask_price": None if evidence.ask_price is None else float(evidence.ask_price),
        "proposal_spot": None if evidence.spot is None else float(evidence.spot),
        "semantic_hash": capability.semantic_hash,
    }


def _execution_context(
    *,
    settings: Settings,
    broker: str,
    account_id: str,
    symbol: str,
    authorized: bool,
    daily: tuple[float, int, float, int],
    open_positions: tuple[Any, ...] | None,
    used_idempotency_keys: frozenset[str],
    daily_state_authoritative: bool,
    emergency_stop: bool | None,
) -> ExecutionContext:
    daily_loss, daily_count, max_daily_loss, max_daily_trades = daily
    return ExecutionContext(
        emergency_stop=emergency_stop,
        daily_loss_percent=daily_loss,
        max_daily_loss_percent=max_daily_loss,
        daily_trade_count=daily_count,
        max_daily_trades=max_daily_trades,
        open_positions=open_positions,
        max_open_positions=1,
        used_idempotency_keys=used_idempotency_keys,
        execution_enabled=authorized,
        dry_run=not authorized,
        broker=broker,
        environment=settings.environment,
        account_id=account_id,
        approved_brokers=frozenset({broker}),
        approved_environments=frozenset({settings.environment}),
        approved_accounts=frozenset({account_id}),
        approved_symbols=frozenset({symbol}),
        daily_state_authoritative=daily_state_authoritative,
    )


def _decision_facts(decision: Any) -> dict[str, Any]:
    return {
        "allowed": bool(decision.allowed),
        "code": decision.code.value,
        "reason": decision.reason,
    }


async def _plan_demo_trade(
    settings: Settings, args: argparse.Namespace, report: DemoTradeReport
) -> None:
    """Gather every preview fact from the broker, then evaluate the policy."""
    broker = report.broker
    mode = report.mode

    # Step 4: connect exactly once through the guarded gateway.
    constructed = get_gateway(settings)
    gateway: _GuardedGateway = (
        _GuardedGateway(constructed)
        if mode == "SUBMIT_ONE"
        else PreviewOnlyGateway(constructed)
    )
    report.record(
        "4-gateway",
        "PASSED",
        gateway_class=type(constructed).__name__,
        wrapper=type(gateway).__name__,
        submission_possible=(mode == "SUBMIT_ONE"),
    )

    async with gateway:
        connected = bool(gateway.inner.is_connected)
        report.record("5-connect", "PASSED" if connected else "FAILED", connected=connected)
        if not connected:
            report.block("5-connect", "Broker gateway did not reach a connected state")
            return

        account = await gateway.get_account_info()
        trade_mode = str(getattr(account, "trade_mode", "") or "").lower()
        identity_facts = {
            "account_id_masked": _mask(account.account_id),
            "server": account.server,
            "currency": account.currency,
            "balance": account.balance,
            "trade_mode": trade_mode or None,
            "gateway_demo_verified": bool(getattr(gateway.inner, "_demo_verified", False)),
        }
        if broker in _MT5_FAMILY and trade_mode != "demo":
            report.block(
                "6-demo-identity",
                f"{broker} account trade mode is {trade_mode or 'unknown'!r}, not 'demo'",
                **identity_facts,
            )
            return
        if broker in _MT5_FAMILY and "WELTRADE" not in str(account.server or "").upper():
            report.block(
                "6-demo-identity",
                "Connected terminal is not a Weltrade server",
                **identity_facts,
            )
            return
        if not identity_facts["gateway_demo_verified"]:
            report.block(
                "6-demo-identity",
                "Gateway did not verify the account as DEMO at connect time",
                **identity_facts,
            )
            return
        report.record("6-demo-identity", "PASSED", **identity_facts)

        # Step 7: broker-confirmed synthetic symbol discovery.
        try:
            if broker == "deriv":
                discovered = await _discover_deriv_symbols(settings)
                source = "deriv active_symbols (market=synthetic_index)"
            else:
                discovered = await asyncio.to_thread(_discover_weltrade_symbols)
                source = "MetaTrader5 symbols_get() synthetic filter"
        except Exception as exc:
            report.block(
                "7-symbol-discovery",
                f"Symbol discovery failed: {type(exc).__name__}: {exc}",
            )
            return
        symbol = _select_symbol(report, broker, source, discovered, args.symbol)
        if symbol is None:
            return

        # Step 8: market data, signal, risk approval and trade plan.
        timeframe = Timeframe(args.timeframe)
        try:
            candles = await gateway.get_candles(symbol, timeframe, args.count)
        except Exception as exc:
            report.block(
                "8-market-data",
                f"Candle retrieval failed for {symbol}: {type(exc).__name__}: {exc}",
            )
            return
        df, frame_facts = _closed_frame(candles, timeframe)
        report.record(
            "8-market-data",
            "PASSED" if df is not None else "BLOCKED",
            symbol=symbol,
            timeframe=timeframe.value,
            **frame_facts,
        )
        if df is None:
            report.block("8-market-data", f"Market data unusable: {frame_facts['status']}")
            return

        regime = detect_regime(df)
        signal = generate_trading_signal(df, symbol, regime=regime)
        latest = df.iloc[-1]
        entry = float(latest["close"])

        history_end = datetime.now(timezone.utc)
        history_start = datetime.combine(history_end.date(), day_start.min, tzinfo=timezone.utc)
        try:
            history = await gateway.get_trade_history_snapshot(
                start=history_start, end=history_end, count=500
            )
            reconcile_daily_history(history.trades, balance=account.balance)
            history_facts = {
                "available": True,
                "trades": len(history.trades),
                "covers_today": history.covers(history_start, history_end),
            }
        except Exception as exc:
            history_facts = {
                "available": False,
                "covers_today": False,
                "reason": f"{type(exc).__name__}: {exc}",
            }
        daily_state_authoritative = bool(history_facts.get("covers_today"))

        risk = approve_trade(
            {"signal": signal.get("signal"), "confidence": signal.get("confidence")},
            df,
            balance=account.balance,
            enforce_limits=True,
        )
        daily = get_reconciled_daily_state()
        risk_facts = {
            "approved": bool(risk.get("approved")),
            "reason": str(risk.get("reason")),
            "reason_code": _reason_code_value(risk),
            "risk_percent": risk.get("risk_percent"),
            "authorized_risk_amount": risk.get("authorized_risk_amount"),
            "regime": str(regime),
            "signal": signal.get("signal"),
            "confidence": signal.get("confidence"),
            "daily_loss_percent": daily[0],
            "daily_trade_count": daily[1],
            "max_daily_loss_percent": daily[2],
            "max_daily_trades": daily[3],
            "daily_history": history_facts,
        }
        report.record(
            "9-risk-approval",
            "PASSED" if risk_facts["approved"] else "BLOCKED",
            **risk_facts,
        )
        if not risk_facts["approved"]:
            report.blockers.append(
                f"Risk engine did not approve the trade: {risk_facts['reason_code']}"
            )
        if not daily_state_authoritative:
            report.blockers.append(
                "Daily trade history does not prove complete coverage for today"
            )

        intelligence = dict(signal.get("intelligence") or {})
        if not any(key in intelligence for key in ("atr", "ATR", "ATR_14")):
            intelligence["atr"] = latest.get("ATR", latest.get("ATR_14"))
        plan = TradePlanBuilder(atr_sl_multiplier=2.0, target_rr=2.0).build(
            symbol=symbol, intelligence=intelligence, signal_dict=signal, price=entry
        )
        plan_valid = bool(plan.is_valid())
        side = (
            OrderSide.BUY
            if plan.signal == "BUY"
            else OrderSide.SELL
            if plan.signal == "SELL"
            else None
        )
        plan_facts = {
            "signal": plan.signal,
            "entry": plan.entry,
            "stop_loss": plan.stop_loss,
            "take_profit": plan.take_profit,
            "risk_reward": plan.risk_reward,
            "is_valid": plan_valid,
            "invalidation": plan.invalidation,
            "warnings": list(plan.warnings),
            "side": side.value if side is not None else None,
        }
        report.record(
            "10-trade-plan", "PASSED" if plan_valid and side is not None else "BLOCKED", **plan_facts
        )
        if side is None:
            report.blockers.append(
                f"Trade plan direction is {plan.signal!r}; only BUY or SELL is executable"
            )
        if not plan_valid:
            report.blockers.append(
                f"Trade plan invariants failed: {plan.invalidation or ', '.join(plan.warnings)}"
            )
        if plan.stop_loss is None or plan.take_profit is None:
            report.blockers.append("Mandatory stop-loss and take-profit are not present")

        report.preview.update(
            {
                "mode": mode,
                "broker": broker,
                "server": account.server,
                "account_id_masked": _mask(account.account_id),
                "account_currency": account.currency,
                "balance": account.balance,
                "demo_verification": identity_facts,
                "symbol": symbol,
                "timeframe": timeframe.value,
                "entry_price": entry,
                "side": plan_facts["side"],
                "stop_loss": plan.stop_loss,
                "take_profit": plan.take_profit,
                "risk_reward": plan.risk_reward,
                "risk": risk_facts,
                "trade_plan": plan_facts,
            }
        )
        if side is None or not plan_valid or plan.stop_loss is None or plan.take_profit is None:
            report.preview["quantity"] = None
            report.preview["instrument_spec"] = None
            report.preview["idempotency_key"] = None
            return

        # Step 11: broker-discovered instrument specification and quantity.
        spec: dict[str, Any] | None = None
        quantity: ExecutionQuantity | None = None
        expected_loss: float | None = None
        authorized_risk = float(risk.get("authorized_risk_amount") or 0.0)
        if broker in _MT5_FAMILY:
            try:
                spec = await _weltrade_instrument_spec(gateway, symbol)
                quantity, quantity_facts, quantity_blocker = await _weltrade_quantity(
                    gateway,
                    spec,
                    side=side,
                    entry=entry,
                    stop_loss=float(plan.stop_loss),
                    take_profit=float(plan.take_profit),
                    authorized_risk=authorized_risk,
                )
            except Exception as exc:
                quantity_facts = {}
                quantity_blocker = (
                    f"Broker instrument specification failed: {type(exc).__name__}: {exc}"
                )
            expected_loss = quantity_facts.get("expected_loss_at_stop")
        else:
            try:
                spec = await _deriv_instrument_spec(
                    gateway, symbol, side, str(account.currency or "USD")
                )
            except Exception as exc:
                spec = None
                quantity_facts = {
                    "reason": f"Deriv contract discovery failed: {type(exc).__name__}: {exc}"
                }
                quantity_blocker = str(quantity_facts["reason"])
            else:
                sizing = authorize_execution_quantity(
                    broker=broker,
                    balance=account.balance,
                    risk_percent=float(risk.get("risk_percent") or settings.risk_percent),
                    entry=entry,
                    stop_loss=float(plan.stop_loss),
                )
                quantity = sizing.quantity
                expected_loss = sizing.expected_loss_at_stop
                quantity_facts = {
                    "quantity_basis": "risk.position_sizing.authorize_execution_quantity",
                    "risk_verifiable": sizing.risk_verifiable,
                    "reason": sizing.reason,
                    "authorized_risk_amount": sizing.authorized_risk_amount,
                    "minimum_stake": spec.get("minimum_quantity"),
                }
                quantity_blocker = None if sizing.risk_verifiable else sizing.reason
                if quantity is None and quantity_blocker is None:
                    quantity_blocker = "Deriv demo quantity is not authorizable"
                # Deriv multiplier contracts interpret stop_loss/take_profit as
                # account-currency amounts, while the canonical trade plan and
                # execution policy use absolute prices.  That conflict is
                # unresolved in this repository, so Deriv submission is refused.
                report.blockers.append(
                    "Deriv stop-loss/take-profit are account-currency amounts, not the "
                    "absolute price levels produced by the canonical trade plan"
                )
                quantity_blocker = quantity_blocker or (
                    "Deriv demo quantity authorization is fail-closed pending a verified loss model"
                )

        report.record(
            "11-instrument-spec",
            "PASSED" if spec is not None else "BLOCKED",
            **(spec or {}),
        )
        quantity_detail = dict(quantity_facts)
        quantity_detail.pop("expected_loss_at_stop", None)
        if quantity_blocker:
            quantity_detail["reason"] = quantity_blocker
        report.record(
            "12-quantity",
            "PASSED" if quantity is not None else "BLOCKED",
            quantity_value=None if quantity is None else quantity.value,
            quantity_unit=None if quantity is None else quantity.unit.value,
            expected_loss_at_stop=expected_loss,
            **quantity_detail,
        )
        if spec is None:
            report.blockers.append("Broker instrument specification is unavailable")
        if quantity is None:
            report.blockers.append(str(quantity_blocker or "Execution quantity is unavailable"))

        if quantity is None or expected_loss is None:
            report.preview["quantity"] = None
            report.preview["instrument_spec"] = spec
            report.preview["idempotency_key"] = None
            return

        idempotency_key = build_execution_idempotency_key(
            symbol=symbol.strip().upper(),
            side=side.value,
            quantity=quantity,
            entry=entry,
            stop_loss=float(plan.stop_loss),
            take_profit=float(plan.take_profit),
            signal_time=latest.get("time", df.index[-1]),
        )
        intent = ExecutionIntent(
            symbol=symbol.strip().upper(),
            side=side,
            quantity=quantity,
            authorized_risk_amount=authorized_risk,
            expected_loss_at_stop=float(expected_loss),
            quantity_risk_verified=True,
            entry=entry,
            stop_loss=float(plan.stop_loss),
            take_profit=float(plan.take_profit),
            idempotency_key=idempotency_key,
            risk_approved=bool(risk.get("approved")),
            order_comment="JQE demo trade test",
        )

        positions = tuple(await gateway.get_positions())
        open_positions = PositionSnapshotAdapter.from_positions(positions)
        emergency_stop = (
            False
            if settings.emergency_stop is EmergencyStopState.CLEAR
            else True
            if settings.emergency_stop is EmergencyStopState.ACTIVE
            else None
        )
        context_kwargs = dict(
            settings=settings,
            broker=broker,
            account_id=account.account_id,
            symbol=symbol.strip().upper(),
            daily=daily,
            open_positions=open_positions,
            daily_state_authoritative=daily_state_authoritative,
            emergency_stop=emergency_stop,
        )
        preview_context = _execution_context(
            authorized=False,
            used_idempotency_keys=frozenset(),
            **context_kwargs,
        )
        submit_context = _execution_context(
            authorized=True,
            used_idempotency_keys=frozenset(),
            **context_kwargs,
        )
        preview_decision = ExecutionPolicy.evaluate(intent, preview_context)
        submit_decision = ExecutionPolicy.evaluate(intent, submit_context)
        report.record(
            "13-policy-preview",
            "PASSED" if not preview_decision.allowed else "FAILED",
            expected_code="DEPLOYMENT_NOT_AUTHORIZED",
            **_decision_facts(preview_decision),
        )
        if preview_decision.allowed:
            report.blockers.append(
                "Preview-mode execution policy unexpectedly allowed the order"
            )
        report.record(
            "14-policy-if-submitted",
            "PASSED" if submit_decision.allowed else "BLOCKED",
            open_positions=len(open_positions or ()),
            **_decision_facts(submit_decision),
        )
        if not submit_decision.allowed:
            report.blockers.append(
                f"Execution policy would reject the order: {submit_decision.code.value}"
            )

        report.preview.update(
            {
                "quantity": {"value": quantity.value, "unit": quantity.unit.value},
                "expected_loss_at_stop": float(expected_loss),
                "authorized_risk_amount": authorized_risk,
                "instrument_spec": spec,
                "order_type": "MARKET",
                "idempotency_key": idempotency_key,
                "open_positions": len(open_positions or ()),
                "policy_preview": _decision_facts(preview_decision),
                "policy_if_submitted": _decision_facts(submit_decision),
            }
        )

        if mode != "SUBMIT_ONE":
            return
        if report.blockers:
            report.record(
                "15-submission",
                "REFUSED",
                reason="Unmet demo-trade gates",
                blockers=list(report.blockers),
                executor_submissions=0,
            )
            return

        reverification = await _reverify_demo(gateway, broker, account)
        report.record("15-demo-reverification", "PASSED", **reverification)

        from execution.executor import AsyncTradeExecutor

        records = SQLiteIntentRecordStore(settings.intent_store_path)
        ledger = SQLitePositionLedger(settings.execution_position_ledger_path)
        executor = _SingleSubmissionExecutor(
            AsyncTradeExecutor(
                gateway,
                records,
                reconciler=get_reconciliation_adapter(
                    broker=broker, gateway=gateway.inner, ledger=ledger
                ),
                reservation_lease_seconds=settings.execution_reservation_lease_seconds,
            )
        )
        result = await executor.submit(intent, submit_context)
        report.submission = {
            "submitted": executor.submissions,
            "state": result.state.value,
            "decision": _decision_facts(result.decision),
            "order_id": result.order_id,
            "reason": result.reason,
            "broker": broker,
            "symbol": intent.symbol,
            "account_id_masked": _mask(account.account_id),
            "order_type": "MARKET",
            "side": side.value,
            "quantity": {"value": quantity.value, "unit": quantity.unit.value},
            "stop_loss": intent.stop_loss,
            "take_profit": intent.take_profit,
            "idempotency_key": idempotency_key,
        }
        report.record(
            "16-submission",
            "PASSED" if executor.submissions == 1 else "FAILED",
            **report.submission,
        )


async def run(args: argparse.Namespace) -> int:
    mode = "SUBMIT_ONE" if args.submit_one_demo_order else "PREVIEW"
    if os.environ.get(_AUTHORIZATION_ENV) != "1":
        print(
            f"BLOCKED: set {_AUTHORIZATION_ENV}=1 to authorize the demo trade workflow"
        )
        return 2
    settings = Settings()
    report = DemoTradeReport(
        broker="unresolved",
        mode=mode,
        started_at=datetime.now(timezone.utc).isoformat(),
    )
    report.record(
        "1-authorization-gate",
        "PASSED",
        authorization_env=_AUTHORIZATION_ENV,
        mode=mode,
        broker_execution_enabled=settings.broker_execution_enabled,
        preview_wrapper=(
            "PreviewOnlyGateway" if mode == "PREVIEW" else "transparent proxy + _SingleSubmissionExecutor"
        ),
    )
    if settings.broker_execution_enabled:
        report.block(
            "1-authorization-gate",
            "JQE_BROKER_EXECUTION_ENABLED must remain false for the demo trade workflow",
        )
        return _finish(report, args, exit_code=2)

    selected = settings.effective_broker
    try:
        requested = normalize_broker_name(args.broker) if args.broker else None
    except Exception as exc:
        report.block("2-broker-selection", f"Unsupported broker: {exc}")
        return _finish(report, args, exit_code=2)
    if selected not in _SUPPORTED_BROKERS:
        report.block(
            "2-broker-selection",
            f"Selected broker {selected!r} is not a supported demo broker "
            f"(supported: {list(_SUPPORTED_BROKERS)}); Simulation is never used as a fallback",
        )
        return _finish(report, args, exit_code=2)
    if requested is not None and requested != selected:
        report.block(
            "2-broker-selection",
            f"Requested broker {requested!r} does not match the selected broker {selected!r}",
        )
        return _finish(report, args, exit_code=2)
    report.broker = selected
    report.record(
        "2-broker-selection",
        "PASSED",
        effective_broker=selected,
        environment=settings.environment,
        selection_store=str(settings.broker_selection_store_path),
    )

    safety = _observe_safety(settings)
    unresolved_count, unresolved_blocker = _unresolved_intents(settings)
    safety["unresolved_intent_store_count"] = unresolved_count
    report.record(
        "3-safety-state",
        "PASSED" if safety["state"] == "OBSERVED" else "BLOCKED",
        **safety,
    )
    if safety["state"] != "OBSERVED":
        report.block(
            "3-safety-state",
            f"Execution safety snapshot is {safety['state']}; a fresh observation is required",
        )
    if safety.get("snapshot_emergency_stop") not in (None, "CLEAR"):
        report.block(
            "3-safety-state",
            f"Emergency stop is {safety['snapshot_emergency_stop']} in the safety snapshot",
        )
    if settings.emergency_stop is not EmergencyStopState.CLEAR:
        report.block(
            "3-safety-state",
            f"Configured emergency stop is {settings.emergency_stop.value}, not CLEAR",
        )
    if unresolved_blocker is not None:
        report.block("3-safety-state", unresolved_blocker)

    emergency_stop_blocked = (
        settings.emergency_stop is not EmergencyStopState.CLEAR
        or safety.get("snapshot_emergency_stop") not in (None, "CLEAR")
    )
    if emergency_stop_blocked or unresolved_blocker is not None:
        report.record(
            "3b-hard-stop",
            "BLOCKED",
            reason="Emergency stop or unresolved durable intent prevents any broker interaction",
            emergency_stop_blocked=emergency_stop_blocked,
            unresolved_intents=unresolved_count,
        )
        return _finish(report, args, exit_code=2)

    try:
        await _plan_demo_trade(settings, args, report)
    except Exception as exc:
        report.block("4-gateway", f"{type(exc).__name__}: {exc}")
    return _finish(report, args, exit_code=None)


def _finish(report: DemoTradeReport, args: argparse.Namespace, *, exit_code: int | None) -> int:
    report.finished_at = datetime.now(timezone.utc).isoformat()
    if report.outcome == "NOT_RUN":
        if report.blockers:
            report.outcome = "PREVIEW_BLOCKED"
        elif report.mode == "SUBMIT_ONE":
            report.outcome = (
                "SUBMITTED_ONE_DEMO_ORDER"
                if report.submission and report.submission.get("submitted") == 1
                else "SUBMISSION_NOT_PERFORMED"
            )
        else:
            report.outcome = "PREVIEW_READY"
    payload = report.to_dict()
    text = json.dumps(payload, indent=2, default=str)
    print(text)
    if args.json_out:
        Path(args.json_out).write_text(text, encoding="utf-8")
    if exit_code is not None:
        return exit_code
    return 0 if report.outcome in ("PREVIEW_READY", "SUBMITTED_ONE_DEMO_ORDER") else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--preview",
        action="store_true",
        help="default: build and print the exact demo order without submitting it",
    )
    group.add_argument(
        "--submit-one-demo-order",
        action="store_true",
        help="submit at most one demo order after every gate passes (requires operator approval)",
    )
    parser.add_argument(
        "--broker",
        choices=_SUPPORTED_BROKERS,
        default=None,
        help="must match the currently selected broker; never overrides it",
    )
    parser.add_argument(
        "--symbol",
        default=None,
        help="broker-confirmed synthetic symbol; must appear in broker discovery",
    )
    parser.add_argument("--timeframe", default="H1", choices=[tf.value for tf in Timeframe])
    parser.add_argument("--count", type=int, default=300)
    parser.add_argument("--json-out", default=None)
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
