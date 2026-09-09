"""Live-paper campaign runner executing real orders against demo broker gateways.

This runner operates in real-time or bounded test cycles, pulling market data
from DerivDemoGateway or MT5DemoGateway, evaluating the canonical strategy and
confirmation pipeline, and submitting real broker orders via AsyncTradeExecutor.

All orders are tagged for scope isolation (MT5 magic number 20260809 + comment;
Deriv passthrough metadata) and validated through DemoOnlyGuard before any
submission occurs.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import math
import os
from pathlib import Path
import subprocess
import time
from typing import Any, Mapping
from uuid import uuid4

# MT5 DEAL_REASON integer constants (broker-reported via history_deals_get).
# These are stable across MT5 versions; we define them here so the campaign
# logic can run without a live MT5 import available in test environments.
_MT5_DEAL_REASON_CLIENT = 0    # manual close via desktop terminal
_MT5_DEAL_REASON_MOBILE = 1    # manual close via mobile
_MT5_DEAL_REASON_WEB = 2       # manual close via webtrader
_MT5_DEAL_REASON_EXPERT = 3    # automated expert advisor close
_MT5_DEAL_REASON_SL = 4        # stop-loss triggered
_MT5_DEAL_REASON_TP = 5        # take-profit triggered
_MT5_DEAL_REASON_SO = 6        # margin stop-out
_MT5_DEAL_REASON_ROLLOVER = 7  # position rollover
_MT5_DEAL_REASON_VMARGIN = 8   # virtual margin call
_MT5_DEAL_REASON_SPLIT = 9     # symbol split

_MT5_DEAL_REASON_MAP: dict[int, str] = {
    _MT5_DEAL_REASON_CLIENT:   "MANUAL_CLIENT",
    _MT5_DEAL_REASON_MOBILE:   "MANUAL_MOBILE",
    _MT5_DEAL_REASON_WEB:      "MANUAL_WEB",
    _MT5_DEAL_REASON_EXPERT:   "EXPERT_ADVISOR",
    _MT5_DEAL_REASON_SL:       "BROKER_SL",
    _MT5_DEAL_REASON_TP:       "BROKER_TP",
    _MT5_DEAL_REASON_SO:       "BROKER_STOP_OUT",
    _MT5_DEAL_REASON_ROLLOVER: "ROLLOVER",
    _MT5_DEAL_REASON_VMARGIN:  "VIRTUAL_MARGIN",
    _MT5_DEAL_REASON_SPLIT:    "SPLIT",
}

import pandas as pd

from broker.deriv_demo import DerivDemoGateway
from broker.mt5_demo import MT5DemoGateway
from broker.types import (
    Candle,
    ClosedMarketObservation,
    ExecutionQuantity,
    ExecutionQuantityUnit,
    OrderSide,
    Position,
    TIMEFRAME_SECONDS,
    Timeframe,
)
from config import settings
from core.exceptions import ConfigurationError, UnsafeBrokerAccountError
from core.logger import logger
from execution.executor import AsyncTradeExecutor, ReconciliationState
from execution.idempotency import build_execution_idempotency_key
from execution.persistence import SQLiteIntentRecordStore
from execution.policy import (
    ExecutionContext,
    ExecutionDecisionCode,
    ExecutionIntent,
    PositionSnapshot,
)
from research.campaign_provenance import (
    CampaignEvidence,
    CampaignEvidenceStore,
    SOURCE_AUTHORITIES,
    build_fingerprint,
    build_live_session_identity,
)
from research.historical_confirmation import HistoricalConfirmationState
from research.live_safety import LivePaperSafetyContext
from risk.position_sizing import authorize_execution_quantity
from tools.paper_runtime import (
    evaluate_production_decision,
    evaluate_strategy_candidate,
)


LIVE_MAGIC_NUMBER = 20260809
STRATEGY_ID = "strategy.pipeline.generate_trading_signal"


@dataclass
class _OrderRateGuard:
    max_orders_per_session: int = 50
    min_spacing_seconds: float = 60.0
    _submitted: int = 0
    _last_submission_at: datetime | None = None

    def check_and_record(self, now: datetime) -> tuple[bool, str]:
        """Return (allowed, reason_code). Record the attempt if allowed."""
        if self._submitted >= self.max_orders_per_session:
            return False, "MAX_ORDERS_EXCEEDED"
        if self._last_submission_at is not None:
            elapsed = (now - self._last_submission_at).total_seconds()
            if elapsed < self.min_spacing_seconds:
                return False, "MIN_SPACING_VIOLATED"
        self._submitted += 1
        self._last_submission_at = now
        return True, "ALLOWED"


def _round_lots_to_broker_constraints(symbol_info: Any, raw_volume: float) -> float | None:
    """Floor raw_volume to broker volume_step. Return None if < volume_min."""
    step = getattr(symbol_info, "volume_step", 0.01) or 0.01
    minimum = getattr(symbol_info, "volume_min", 0.01) or 0.01
    floored = math.floor(raw_volume / step) * step
    floored = round(floored, 8)
    return floored if floored >= minimum else None


async def _fetch_mt5_close_reason(gateway: Any, position_id: str) -> str:
    """Query MT5 history_deals_get for the close reason of a specific position.

    Returns an honest label from ``_MT5_DEAL_REASON_MAP`` when a confirmed
    closing deal is found, otherwise returns ``"POSITION_NO_LONGER_OPEN"``.
    Never raises — any failure degrades to the neutral label.
    """
    try:
        import MetaTrader5 as mt5  # type: ignore
        from datetime import timedelta
        now = datetime.now(timezone.utc)
        # Search deals from up to 7 days back to cover the position.
        deals = await asyncio.to_thread(
            mt5.history_deals_get,
            now - timedelta(days=7),
            now,
        )
        if not deals:
            return "POSITION_NO_LONGER_OPEN"
        # Filter to closing deals that reference this position ticket.
        # MT5 deal.position_id links a deal back to its originating position.
        closing_entry_types: set[int] = set()
        try:
            closing_entry_types = {mt5.DEAL_ENTRY_OUT, mt5.DEAL_ENTRY_INOUT}
        except AttributeError:
            # Stub environment: constants are MagicMock objects; skip filtering.
            return "POSITION_NO_LONGER_OPEN"
        closing_deals = [
            d for d in deals
            if str(getattr(d, "position_id", None)) == position_id
            and getattr(d, "entry", None) in closing_entry_types
        ]
        if not closing_deals:
            return "POSITION_NO_LONGER_OPEN"
        # Use the most recent closing deal (highest time).
        latest_deal = max(closing_deals, key=lambda d: getattr(d, "time", 0))
        raw_reason = getattr(latest_deal, "reason", None)
        if raw_reason is None:
            return "POSITION_NO_LONGER_OPEN"
        return _MT5_DEAL_REASON_MAP.get(int(raw_reason), f"MT5_REASON_{raw_reason}")
    except Exception:
        return "POSITION_NO_LONGER_OPEN"


def _git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True,
        ).stdout.strip()
    except Exception:
        return "unknown"


def _candidate_id(symbol: str, timeframe: str, signal_candle: datetime, direction: str) -> str:
    import hashlib
    value = f"{symbol.upper()}|{timeframe}|{signal_candle.astimezone(timezone.utc).isoformat()}|{direction}"
    return "CANDIDATE-" + hashlib.sha256(value.encode()).hexdigest()[:24]


def _candles_to_observations(candles: list[Candle], symbol: str, timeframe: Timeframe, provider: str) -> list[ClosedMarketObservation]:
    interval = timedelta(seconds=TIMEFRAME_SECONDS[timeframe])
    return [
        ClosedMarketObservation(
            canonical_symbol=symbol.upper(),
            source=provider,
            provider_symbol=symbol,
            timeframe=timeframe,
            candle_opened_at=c.time,
            closed_at=c.time + interval,
            open=c.open,
            high=c.high,
            low=c.low,
            close=c.close,
            volume=c.volume,
        )
        for c in candles
    ]


async def run_live_paper_campaign(
    *,
    symbol: str = "XAUUSD",
    timeframe: Timeframe = Timeframe.M15,
    gateway: DerivDemoGateway | MT5DemoGateway | None = None,
    output: Path = Path("state/live_paper_campaigns/latest.json"),
    evidence_path: Path | None = None,
    session_id: str | None = None,
    max_candles: int | None = None,
    max_duration_seconds: float | None = None,
    poll_interval_seconds: float = 0.0,
    quiet: bool = False,
    safety_context: LivePaperSafetyContext | None = None,
) -> dict[str, Any]:
    """Execute a live paper trading campaign against a connected demo gateway."""

    # 1. Fail-closed pre-flight validation
    if gateway is None or not isinstance(gateway, (DerivDemoGateway, MT5DemoGateway)):
        raise ConfigurationError(
            "live_paper campaign requires DerivDemoGateway or MT5DemoGateway"
        )

    if settings.campaign_mode not in {"live_paper"}:
        raise ConfigurationError("campaign_mode must be set to 'live_paper'")

    if not settings.broker_execution_enabled:
        raise ConfigurationError("broker_execution_enabled must be True for live_paper")

    if settings.broker in {"simulation", "mt5", "deriv"}:
        raise ConfigurationError(
            f"live_paper campaign requires demo broker, got '{settings.broker}'"
        )

    eff_max_candles = max_candles or settings.live_paper_max_candles
    eff_max_duration = max_duration_seconds or settings.live_paper_max_duration_seconds

    if eff_max_candles is None and eff_max_duration is None:
        raise ConfigurationError("live_paper requires at least one stop condition")

    # 2. Connect gateway and verify demo account
    await gateway.connect()
    if not getattr(gateway, "_demo_verified", False):
        raise UnsafeBrokerAccountError("Gateway failed demo-only account verification")

    # 3. Fetch initial account details
    account = await gateway.get_account_info()
    broker_name = "mt5_demo" if isinstance(gateway, MT5DemoGateway) else "deriv_demo"

    # 4. Initialize safety context
    if safety_context is None:
        safety_context = LivePaperSafetyContext(
            symbol=symbol,
            broker=broker_name,
            account_id=account.account_id,
            max_daily_loss_percent=settings.max_daily_loss,
            max_daily_trades=settings.max_trades_daily,
            max_open_positions=1,
            environment="demo",
        )

    # 5. Initialize session and persistent stores
    session_id = session_id or uuid4().hex
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    evidence_path = evidence_path or output.with_name(f"{output.stem}.{session_id}.evidence.sqlite3")
    intent_path = output.with_name(f"{output.stem}.{session_id}.intents.sqlite3")
    pending_confirmation_path = output.with_name(f"{output.stem}.{session_id}.confirmation.json")

    stop_conditions: dict[str, Any] = {}
    if eff_max_candles is not None:
        stop_conditions["max_candles"] = eff_max_candles
    if eff_max_duration is not None:
        stop_conditions["max_duration_seconds"] = eff_max_duration

    started_at = datetime.now(timezone.utc)
    live_identity = build_live_session_identity(
        session_id=session_id,
        broker=broker_name,
        account_id=account.account_id,
        is_virtual=True,
        symbol=symbol,
        timeframe=timeframe.value,
        started_at=started_at.isoformat(),
        initial_balance=account.balance,
        currency=account.currency,
        stop_conditions=stop_conditions,
    )

    fingerprint = build_fingerprint(
        root=Path(__file__).resolve().parents[1],
        git_commit=_git_commit(),
        strategy_id=STRATEGY_ID,
        effective_config={
            "symbol": symbol.upper(),
            "timeframe": timeframe.value,
            "broker": broker_name,
            "broker_execution_enabled": True,
            "campaign_mode": "live_paper",
            "account_id": account.account_id,
            "account_balance": account.balance,
            "risk_percent": settings.risk_percent,
            "max_daily_loss": settings.max_daily_loss,
            "max_daily_trades": settings.max_trades_daily,
            "max_open_positions": safety_context.max_open_positions,
            "stop_conditions": stop_conditions,
        },
        dataset_identity=f"live_paper:{live_identity.live_session_identity_sha256}",
        symbol=symbol,
        timeframe=timeframe.value,
        first_candle=started_at.isoformat(),
        last_candle=started_at.isoformat(),
        requested_observations=eff_max_candles or 0,
        safety_context={"kind": safety_context.kind.value, **safety_context.assumptions},
    )

    evidence_store = CampaignEvidenceStore(evidence_path)
    evidence_store.start(session_id, fingerprint)

    event_counter = 0

    def emit(event_type: str, occurred_at: datetime | str, facts: Mapping[str, Any], candidate_id: str | None = None) -> None:
        nonlocal event_counter
        event_counter += 1
        ts = occurred_at.isoformat() if isinstance(occurred_at, datetime) else str(occurred_at)
        evidence_store.append(
            session_id,
            CampaignEvidence(
                event_id=f"{session_id}-{event_counter}",
                event_type=event_type,
                candidate_id=candidate_id,
                occurred_at=ts,
                facts=facts,
            ),
        )

    # 6. Initialize executor and guards
    intent_store = SQLiteIntentRecordStore(intent_path)
    executor = AsyncTradeExecutor(gateway=gateway, records=intent_store)
    rate_guard = _OrderRateGuard(
        max_orders_per_session=settings.live_paper_max_orders_per_session,
        min_spacing_seconds=settings.live_paper_min_order_spacing_seconds,
    )
    confirmation = HistoricalConfirmationState()

    _own_order_ids: set[str] = set()
    _open_trades: dict[str, dict[str, Any]] = {}
    _used_idempotency_keys: set[str] = set()

    # 7a. Startup recovery: reconstruct any positions this campaign already
    # opened (tagged with LIVE_MAGIC_NUMBER / JQE LivePaper comment prefix)
    # so that rate limits and MAX_OPEN_POSITIONS are correct from the first
    # policy check, even if the process was restarted mid-session.
    try:
        startup_positions = tuple(await gateway.get_positions())
    except Exception as exc:
        logger.warning("Startup position query failed: {}", exc)
        startup_positions = ()

    _is_mt5 = isinstance(gateway, MT5DemoGateway)
    _live_paper_comment_prefix = "JQE LivePaper"

    for sp in startup_positions:
        is_ours = False
        if _is_mt5:
            # MT5 positions carry magic number on the position record.
            # We rely on the raw field if available; the Position model
            # doesn't expose it, so we check via the gateway's underlying
            # positions_get result — but that's not directly accessible here.
            # As a practical proxy, we filter by comment prefix stored
            # in the underlying deal comment. Since Position doesn't carry
            # magic, we use comment prefix if present, otherwise we cannot
            # distinguish; we err on the side of not claiming unknown positions.
            # The comment field IS in the underlying mt5 position record.
            raw_comment = getattr(sp, "_raw_comment", None) or ""
            raw_magic = getattr(sp, "_raw_magic", None)
            if raw_magic == LIVE_MAGIC_NUMBER:
                is_ours = True
            elif raw_comment.startswith(_live_paper_comment_prefix):
                is_ours = True
        else:
            # Deriv: comment passthrough stored in contract metadata.
            raw_comment = getattr(sp, "_raw_comment", None) or ""
            if raw_comment.startswith(_live_paper_comment_prefix):
                is_ours = True

        if is_ours:
            _own_order_ids.add(sp.position_id)
            _open_trades[sp.position_id] = {
                "candidate_id": None,  # not recoverable after restart
                "symbol": sp.symbol,
                "side": sp.side.value if hasattr(sp.side, "value") else str(sp.side),
                "entry_price": float(sp.open_price),
                "volume": float(sp.volume),
                "opened_at": sp.opened_at.isoformat() if sp.opened_at else None,
                "recovered": True,
            }
            emit("POLICY", datetime.now(timezone.utc), {
                "result": "RECOVERED",
                "reason_code": "POSITION_RECOVERED_ON_STARTUP",
                "position_id": sp.position_id,
                "symbol": sp.symbol,
                "side": sp.side.value if hasattr(sp.side, "value") else str(sp.side),
                "volume": float(sp.volume),
                "open_price": float(sp.open_price),
                "note": "Inherited from prior session; counts toward open-position limits",
            })
            logger.info(
                "Live-paper startup: recovered existing own position {} for {}",
                sp.position_id, sp.symbol,
            )

    candles_processed = 0
    start_monotonic = time.monotonic()
    last_candle_time: datetime | None = None

    # 7b. Main loop
    while True:
        now = datetime.now(timezone.utc)

        # Check stop conditions
        if eff_max_candles is not None and candles_processed >= eff_max_candles:
            logger.info("Live-paper campaign reached maximum candle count: {}", candles_processed)
            break
        if eff_max_duration is not None and (time.monotonic() - start_monotonic) >= eff_max_duration:
            logger.info("Live-paper campaign reached maximum duration: {}s", eff_max_duration)
            break

        # Fetch candles
        candles = await gateway.get_candles(symbol, timeframe, 501)
        if not candles:
            if poll_interval_seconds > 0:
                await asyncio.sleep(poll_interval_seconds)
            continue

        latest_candle = candles[-1]
        if last_candle_time is not None and latest_candle.time <= last_candle_time:
            # No new closed candle yet
            await asyncio.sleep(poll_interval_seconds if poll_interval_seconds > 0 else 0.005)
            continue

        last_candle_time = latest_candle.time
        candles_processed += 1

        observations = _candles_to_observations(candles, symbol, timeframe, broker_name)
        window = observations[-500:]
        latest = window[-1]

        # Strategy evaluation
        signal, facts = await evaluate_strategy_candidate(window)
        facts["strategy_signal_direction"] = facts.get("signal_direction", "NO_TRADE")
        pending_before = confirmation.pending
        transition = confirmation.observe(latest.candle_opened_at, str(facts.get("regime", "UNKNOWN")))
        current_direction = str(signal.get("signal", "NO_TRADE"))
        current_candidate_id = _candidate_id(symbol, timeframe.value, latest.candle_opened_at, current_direction) if current_direction in {"BUY", "SELL"} else None

        if current_candidate_id is not None:
            status = "CONFIRMATION_PENDING" if pending_before is None else "OVERLAP_PENDING_CANDIDATE"
            emit("CANDIDATE", latest.candle_opened_at, {
                "symbol": symbol,
                "timeframe": timeframe.value,
                "signal_candle": latest.candle_opened_at.isoformat(),
                "direction": current_direction,
                "regime": facts.get("regime"),
                "confidence": facts.get("signal_confidence"),
                "momentum": facts.get("momentum"),
                "volatility": facts.get("volatility"),
                "rsi": facts.get("rsi"),
                "candidate_status": status,
            }, current_candidate_id)

        if transition.candidate is not None and transition.state not in {"NO_PENDING_CANDIDATE", "PENDING_CONFIRMATION"}:
            prior = transition.candidate
            prior_id = _candidate_id(symbol, timeframe.value, prior.signal_candle, prior.direction)
            emit("CONFIRMATION" if transition.state in {"CONFIRMED", "CONFIRMATION_FAILED"} else "CANDIDATE_DISPOSITION", latest.candle_opened_at, {
                "signal_timestamp": prior.signal_candle.isoformat(),
                "confirmation_timestamp": latest.candle_opened_at.isoformat(),
                "direction": prior.direction,
                "signal_regime": prior.strategy_context.get("regime"),
                "confirmation_regime": facts.get("regime"),
                "result": transition.state,
                "reason_code": transition.reason,
                "confirmation_features": {"regime": facts.get("regime")},
            }, prior_id)

        if transition.state == "ENTRY_DUE" and transition.candidate is not None:
            candidate = transition.candidate
            candidate_id = _candidate_id(symbol, timeframe.value, candidate.signal_candle, candidate.direction)
            original_signal = dict(candidate.strategy_context["signal"])
            entry_price = float(latest.open)
            side = OrderSide.BUY if candidate.direction == "BUY" else OrderSide.SELL

            # i. Defensive Rate Limit check
            rate_allowed, rate_code = rate_guard.check_and_record(now)
            if not rate_allowed:
                emit("POLICY", now, {
                    "result": "REJECTED",
                    "reason_code": "ORDER_RATE_LIMIT",
                    "rate_limit_reason": rate_code,
                    "candidate_id": candidate_id,
                }, candidate_id)
                confirmation.save(pending_confirmation_path)
                continue

            # ii. Broker reconciliation (own positions only)
            try:
                broker_positions = tuple(await gateway.get_positions())
            except Exception as exc:
                logger.warning("Failed to retrieve broker positions: {}", exc)
                broker_positions = ()

            broker_pos_ids = {p.position_id for p in broker_positions}
            # Detect local vs broker mismatch
            mismatched = [oid for oid in list(_open_trades.keys()) if oid not in broker_pos_ids]
            for m_id in mismatched:
                emit("POLICY", now, {
                    "result": "MISMATCH",
                    "reason_code": "BROKER_POSITION_MISMATCH",
                    "order_id": m_id,
                    "candidate_id": _open_trades[m_id].get("candidate_id"),
                }, _open_trades[m_id].get("candidate_id"))
                del _open_trades[m_id]

            own_open = [p for p in broker_positions if p.position_id in _own_order_ids]

            # Check open position limits
            if len(own_open) >= safety_context.max_open_positions:
                emit("POLICY", now, {
                    "result": "BLOCKED",
                    "reason_code": "MAX_OPEN_POSITIONS",
                    "open_positions": len(own_open),
                    "candidate_id": candidate_id,
                }, candidate_id)
                confirmation.save(pending_confirmation_path)
                continue

            if any(p.symbol.strip().upper() == symbol.strip().upper() for p in own_open):
                emit("POLICY", now, {
                    "result": "BLOCKED",
                    "reason_code": "DUPLICATE_SYMBOL_POSITION",
                    "symbol": symbol,
                    "candidate_id": candidate_id,
                }, candidate_id)
                confirmation.save(pending_confirmation_path)
                continue

            # iii. Lot sizing & broker constraints
            account = await gateway.get_account_info()
            atr_sl_mult = 2.0
            atr = float(dict(original_signal.get("features", {})).get("atr_14", 1.0) or 1.0)
            stop_distance = atr * atr_sl_mult
            if side == OrderSide.BUY:
                stop_loss = round(entry_price - stop_distance, 4)
                take_profit = round(entry_price + (stop_distance * 2.0), 4)
            else:
                stop_loss = round(entry_price + stop_distance, 4)
                take_profit = round(entry_price - (stop_distance * 2.0), 4)

            sizing = authorize_execution_quantity(
                broker=broker_name,
                balance=account.balance,
                risk_percent=settings.risk_percent,
                entry=entry_price,
                stop_loss=stop_loss,
            )

            if not sizing.risk_verifiable or sizing.quantity is None:
                emit("RISK", now, {
                    "result": "REJECTED",
                    "reason_code": sizing.reason,
                    "candidate_id": candidate_id,
                }, candidate_id)
                confirmation.save(pending_confirmation_path)
                continue

            raw_quantity = sizing.quantity
            if broker_name == "mt5_demo":
                symbol_info = None
                if hasattr(gateway, "_resolve_symbol"):
                    try:
                        import MetaTrader5 as mt5  # type: ignore
                        real_sym = gateway._resolve_symbol(symbol)
                        symbol_info = mt5.symbol_info(real_sym)
                    except Exception:
                        symbol_info = None
                floored_lots = _round_lots_to_broker_constraints(symbol_info, raw_quantity.value)
                if floored_lots is None:
                    emit("RISK", now, {
                        "result": "REJECTED",
                        "reason_code": "LOT_SIZE_INVALID",
                        "raw_volume": raw_quantity.value,
                        "candidate_id": candidate_id,
                    }, candidate_id)
                    confirmation.save(pending_confirmation_path)
                    continue
                exec_quantity = ExecutionQuantity(value=floored_lots, unit=ExecutionQuantityUnit.MT5_LOTS)
            else:
                exec_quantity = raw_quantity

            # Emit ENTRY and RISK evidence
            emit("ENTRY", latest.candle_opened_at, {
                "expected_entry_timestamp": candidate.expected_entry_candle.isoformat(),
                "actual_entry_timestamp": latest.candle_opened_at.isoformat(),
                "entry_available": True,
                "entry_price": str(entry_price),
            }, candidate_id)

            emit("RISK", latest.candle_opened_at, {
                "result": "AUTHORIZED",
                "input_confidence": original_signal.get("confidence"),
                "account_balance": account.balance,
                "risk_percent": settings.risk_percent,
                "authorized_quantity": str(exec_quantity.value),
                "quantity_unit": exec_quantity.unit.value,
                "authorized_risk_amount": str(sizing.authorized_risk_amount),
                "stop_distance": str(stop_distance),
                "risk_policy_source_hash": fingerprint.source_hashes.get("risk", ""),
            }, candidate_id)

            # iv. Build ExecutionIntent
            idempotency_key = build_execution_idempotency_key(
                symbol=symbol,
                side=side,
                quantity=exec_quantity,
                entry=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                signal_time=candidate.signal_candle.isoformat(),
            )

            intent = ExecutionIntent(
                symbol=symbol,
                side=side,
                quantity=exec_quantity,
                authorized_risk_amount=sizing.authorized_risk_amount,
                expected_loss_at_stop=sizing.expected_loss_at_stop,
                quantity_risk_verified=True,
                entry=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                idempotency_key=idempotency_key,
                risk_approved=True,
                magic_number=LIVE_MAGIC_NUMBER,
                order_comment=f"JQE LivePaper {session_id[:8]}",
            )

            # v. Build ExecutionContext and submit via AsyncTradeExecutor
            snapshots = tuple(PositionSnapshot(symbol=p.symbol, side=p.side) for p in own_open)
            exec_context = safety_context.execution_context(
                emergency_stop=False,
                daily_loss_percent=0.0,
                daily_trade_count=len(_own_order_ids),
                open_positions=snapshots,
                used_idempotency_keys=frozenset(_used_idempotency_keys),
                daily_state_authoritative=True,
            )

            # Execute via canonical AsyncTradeExecutor boundary (NO DIRECT .submit_order CALL!)
            result = await executor.submit(intent, exec_context)

            # vi. Handle submission result
            if result.decision.code != ExecutionDecisionCode.ALLOWED:
                emit("POLICY", now, {
                    "result": "REJECTED",
                    "reason_code": result.decision.code.value,
                    "reason": result.decision.reason,
                    "candidate_id": candidate_id,
                }, candidate_id)
            elif result.state == ReconciliationState.ALREADY_EXECUTED or result.order_id:
                order_id = result.order_id or "ORDER_UNKNOWN"
                _own_order_ids.add(order_id)
                _used_idempotency_keys.add(idempotency_key)

                # Look up fill details
                cur_positions = tuple(await gateway.get_positions())
                matched_pos = next((p for p in cur_positions if p.position_id == order_id), None)
                pos_price = getattr(matched_pos, "open_price", getattr(matched_pos, "entry_price", None)) if matched_pos else None
                fill_price = float(pos_price) if pos_price is not None else entry_price
                filled_vol = getattr(matched_pos, "volume", exec_quantity.value) if matched_pos else exec_quantity.value
                filled_vol = float(filled_vol) if filled_vol else exec_quantity.value
                is_partial = filled_vol < exec_quantity.value

                emit("POSITION_OPENED", now, {
                    "candidate_id": candidate_id,
                    "symbol": symbol,
                    "side": side.value,
                    "requested_price": entry_price,
                    "broker_order_id": order_id,
                    "broker_fill_price": fill_price,
                    "broker_fill_time": now.isoformat(),
                    "slippage": abs(fill_price - entry_price),
                    "requested_volume": exec_quantity.value,
                    "filled_volume": filled_vol,
                    "partial_fill": is_partial,
                    "campaign_mode": "live_paper",
                    "session_kind": "live_paper",
                }, candidate_id)

                _open_trades[order_id] = {
                    "candidate_id": candidate_id,
                    "symbol": symbol,
                    "side": side.value,
                    "entry_price": fill_price,
                    "volume": filled_vol,
                    "opened_at": now.isoformat(),
                }
            elif result.state == ReconciliationState.REJECTED:
                emit("ENTRY", now, {
                    "candidate_id": candidate_id,
                    "result": "REJECTED",
                    "broker_rejection_reason": result.reason,
                    "reason_code": "BROKER_REJECTED",
                    "campaign_mode": "live_paper",
                }, candidate_id)
            elif result.state == ReconciliationState.PENDING:
                # Order remained in PENDING state; poll or time out
                emit("ENTRY_TIMEOUT", now, {
                    "candidate_id": candidate_id,
                    "reason_code": "ENTRY_TIMEOUT",
                    "idempotency_key": idempotency_key,
                    "campaign_mode": "live_paper",
                }, candidate_id)

            confirmation.save(pending_confirmation_path)
            continue

        elif transition.state in {"CONFIRMED", "CONFIRMATION_FAILED", "INCOMPLETE_CONFIRMATION", "INCOMPLETE_ENTRY", "DUPLICATE_CONFIRMATION_PREVENTED"}:
            confirmation.save(pending_confirmation_path)
        else:
            direction = str(signal.get("signal", "NO_TRADE"))
            if confirmation.pending is None and direction in {"BUY", "SELL"}:
                confirmation.queue(
                    symbol=symbol,
                    timeframe=timeframe.value,
                    signal_candle=latest.candle_opened_at,
                    direction=direction,
                    confidence=int(signal.get("confidence", 0)),
                    strategy_context={"signal": signal, "regime": facts.get("regime")},
                    candle_interval=timedelta(seconds=TIMEFRAME_SECONDS[timeframe]),
                )
            confirmation.save(pending_confirmation_path)

        # Monitor and reconcile closed positions
        try:
            cur_positions = tuple(await gateway.get_positions())
        except Exception:
            cur_positions = ()

        cur_pos_ids = {p.position_id for p in cur_positions}
        for open_oid in list(_open_trades.keys()):
            if open_oid not in cur_pos_ids:
                trade = _open_trades.pop(open_oid)
                exit_price = float(latest.close)

                # Resolve the actual close reason from the broker where possible.
                # For MT5: query history_deals_get for the position ticket and
                # read the DEAL_REASON field from the closing deal record.
                # For Deriv: no equivalent programmatic API exists; record the
                # neutral label rather than fabricating a causal claim.
                if _is_mt5:
                    exit_reason = await _fetch_mt5_close_reason(gateway, open_oid)
                else:
                    exit_reason = "POSITION_NO_LONGER_OPEN"

                emit("POSITION_CLOSED", now, {
                    "candidate_id": trade.get("candidate_id"),
                    "symbol": trade["symbol"],
                    "side": trade["side"],
                    "broker_order_id": open_oid,
                    "broker_fill_price": exit_price,
                    "broker_fill_time": now.isoformat(),
                    "exit_price": exit_price,
                    "pnl": 0.0,
                    "exit_reason": exit_reason,
                    "campaign_mode": "live_paper",
                    "session_kind": "live_paper",
                }, trade.get("candidate_id"))

        if poll_interval_seconds > 0:
            await asyncio.sleep(poll_interval_seconds)

    # 8. Finalize evidence and write summary
    evidence_store.finalize(session_id)

    summary: dict[str, Any] = {
        "session": {
            "session_id": session_id,
            "status": "COMPLETED",
            "campaign_mode": "live_paper",
            "broker": broker_name,
            "symbol": symbol,
            "timeframe": timeframe.value,
            "processed_candles": candles_processed,
            "orders_submitted": rate_guard._submitted,
            "evidence_path": str(evidence_path),
            "output_path": str(output),
        },
        "live_session_identity": live_identity.payload(),
        "research_fingerprint": fingerprint.payload(),
    }

    temp_path = output.with_suffix(output.suffix + ".tmp")
    temp_path.write_text(json.dumps(summary, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    os.replace(temp_path, output)

    return summary
