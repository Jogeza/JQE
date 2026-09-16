"""Live-paper campaign runner executing real orders against demo broker gateways.

This runner operates in real-time or bounded test cycles, pulling market data
from DerivDemoGateway or MT5DemoGateway, evaluating the canonical strategy and
confirmation pipeline, and submitting real broker orders via AsyncTradeExecutor.

Campaign-opened position identifiers are durably recorded in an instance-scoped
SQLite ledger and reconciled with broker state after restart. MT5 tags remain a
secondary recovery path for the narrow crash window between broker acceptance
and the ledger write. Every submission is validated through DemoOnlyGuard.
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
    AccountIdentity,
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
from data.market_observation import closed_observations_from_candles, provider_symbol_for
from execution.executor import AsyncTradeExecutor, ReconciliationState
from execution.idempotency import build_execution_idempotency_key
from execution.persistence import (
    SQLiteIntentRecordStore,
    SQLiteOneShotExecutionGuard,
    SQLitePositionLedger,
)
from execution.policy import (
    ExecutionContext,
    ExecutionDecisionCode,
    ExecutionIntent,
    PositionSnapshot,
)
from notifications.events import JQENotificationEvents
from notifications.service import NotificationService
from notifications.telegram import TelegramConfigurationError, telegram_gateway_from_settings
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


def _signal_freshness(
    observation: ClosedMarketObservation, observed_at: datetime
) -> tuple[str, datetime]:
    """Classify signal data against a one-timeframe closed-candle validity window."""
    expires_at = observation.closed_at + timedelta(
        seconds=TIMEFRAME_SECONDS[observation.timeframe]
    )
    if observed_at < observation.closed_at:
        return "degraded", expires_at
    if observed_at <= expires_at:
        return "fresh", expires_at
    return "stale", expires_at


@dataclass
class _OrderSpacingGuard:
    """Throttle submission timing only; the durable lifetime guard owns quantity."""

    min_spacing_seconds: float = 60.0
    _last_submission_at: datetime | None = None

    def check_and_record(self, now: datetime) -> tuple[bool, str]:
        """Return whether the minimum spacing permits an attempted submission."""
        if self._last_submission_at is not None:
            elapsed = (now - self._last_submission_at).total_seconds()
            if elapsed < self.min_spacing_seconds:
                return False, "MIN_SPACING_VIOLATED"
        self._last_submission_at = now
        return True, "ALLOWED"


@dataclass(frozen=True, slots=True)
class _MT5CloseReconciliation:
    state: str
    reason: str
    pnl: float | None = None
    exit_price: float | None = None
    closed_at: datetime | None = None


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


async def _reconcile_mt5_close(
    gateway: Any,
    position_id: str,
    *,
    timeout_seconds: float,
) -> _MT5CloseReconciliation:
    """Poll MT5 deal history for authoritative close price and account P&L."""
    import MetaTrader5 as mt5  # type: ignore

    deadline = time.monotonic() + timeout_seconds
    poll_seconds = max(0.01, min(float(getattr(gateway, "_tick_poll_interval", 0.25)), timeout_seconds))
    while True:
        now = datetime.now(timezone.utc)
        try:
            deals = await asyncio.to_thread(
                mt5.history_deals_get, now - timedelta(days=7), now
            )
            closing_types = {mt5.DEAL_ENTRY_OUT, mt5.DEAL_ENTRY_INOUT}
            matches = [
                deal for deal in (deals or ())
                if str(getattr(deal, "position_id", "")) == str(position_id)
                and getattr(deal, "entry", None) in closing_types
            ]
            monetary = [
                deal for deal in matches
                if isinstance(getattr(deal, "profit", None), (int, float))
            ]
            if matches and monetary:
                latest = max(matches, key=lambda deal: getattr(deal, "time", 0))
                pnl = sum(
                    float(getattr(deal, "profit", 0.0))
                    + float(getattr(deal, "commission", 0.0) or 0.0)
                    + float(getattr(deal, "swap", 0.0) or 0.0)
                    + float(getattr(deal, "fee", 0.0) or 0.0)
                    for deal in monetary
                )
                raw_reason = getattr(latest, "reason", None)
                reason = (
                    _MT5_DEAL_REASON_MAP.get(int(raw_reason), f"MT5_REASON_{raw_reason}")
                    if raw_reason is not None
                    else "POSITION_NO_LONGER_OPEN"
                )
                raw_time = getattr(latest, "time", None)
                closed_at = (
                    datetime.fromtimestamp(raw_time, tz=timezone.utc)
                    if isinstance(raw_time, (int, float))
                    else now
                )
                raw_price = getattr(latest, "price", None)
                exit_price = float(raw_price) if isinstance(raw_price, (int, float)) else None
                return _MT5CloseReconciliation(
                    "RECONCILED", reason, pnl, exit_price, closed_at
                )
        except Exception as exc:
            logger.warning("MT5 close-history reconciliation attempt failed: {}", exc)
        if time.monotonic() >= deadline:
            return _MT5CloseReconciliation(
                "PENDING", "MT5_CLOSE_HISTORY_PENDING"
            )
        await asyncio.sleep(poll_seconds)


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
    ledger_path: Path | None = None,
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

    broker_name = "mt5_demo" if isinstance(gateway, MT5DemoGateway) else "deriv_demo"
    if settings.broker != broker_name:
        raise ConfigurationError(
            f"live_paper gateway/configuration mismatch: gateway={broker_name}, configured={settings.broker}"
        )
    if broker_name == "deriv_demo" and settings.deriv_expected_environment != "demo":
        raise ConfigurationError("Deriv live-paper requires unmistakable DEMO environment")

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
    account_identity = AccountIdentity(
        broker="mt5" if broker_name == "mt5_demo" else "deriv",
        account_id=account.account_id,
        server=account.server,
        currency=account.currency,
        trade_mode=account.trade_mode or "demo",
    )
    mt5_preflight: Mapping[str, Any] | None = None
    if broker_name == "mt5_demo":
        mt5_preflight = await gateway.verify_instrument_risk_spec(symbol)

    # Notifications are downstream observations only. Configuration or delivery
    # failure must never grant authority, submit an order, or stop the campaign.
    try:
        telegram_gateway = telegram_gateway_from_settings(settings)
    except TelegramConfigurationError:
        logger.warning("Telegram signal notifications are unavailable: invalid configuration")
        telegram_gateway = None
    notification_events = JQENotificationEvents(NotificationService(telegram_gateway))

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
    ledger_path = ledger_path or output.with_name(f"{output.stem}.positions.sqlite3")
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

    if mt5_preflight is not None:
        emit("POLICY", datetime.now(timezone.utc), {
            "result": "AUTHORIZED",
            "reason_code": "MT5_INSTRUMENT_RISK_PREFLIGHT_VERIFIED",
            **{key: value for key, value in mt5_preflight.items() if key != "account_currency"},
        })

    def emit_position_snapshot(positions: tuple[Position, ...], observed_at: datetime) -> None:
        """Persist broker-observed position fields for read-only monitors."""
        emit("POSITION_SNAPSHOT", observed_at, {
            "positions": [
                {
                    "position_id": position.position_id,
                    "symbol": position.symbol,
                    "side": position.side.value,
                    "volume": float(position.volume),
                    "open_price": float(position.open_price),
                    "current_price": position.current_price,
                    "stop_loss": position.stop_loss,
                    "take_profit": position.take_profit,
                    "opened_at": position.opened_at.isoformat() if position.opened_at else None,
                }
                for position in positions
            ],
        })

    # 6. Initialize executor and guards
    intent_store = SQLiteIntentRecordStore(intent_path)
    position_ledger = SQLitePositionLedger(ledger_path)
    executor = AsyncTradeExecutor(gateway=gateway, records=intent_store)
    spacing_guard = _OrderSpacingGuard(
        min_spacing_seconds=settings.live_paper_min_order_spacing_seconds,
    )
    lifetime_guard = SQLiteOneShotExecutionGuard(settings.execution_lifetime_store_path)
    submissions_started = 0
    confirmation = HistoricalConfirmationState()

    _own_order_ids: set[str] = set()
    _open_trades: dict[str, dict[str, Any]] = {}
    _used_idempotency_keys: set[str] = set()

    # 7a. Startup recovery: broker state is authoritative; the stable local
    # ledger identifies positions opened by this live-paper instance.
    ledger_open = position_ledger.open_entries(broker=broker_name)
    startup_query_succeeded = False
    try:
        startup_positions = tuple(await gateway.get_positions())
        startup_query_succeeded = True
    except Exception as exc:
        logger.warning("Startup position query failed: {}", exc)
        startup_positions = ()

    _is_mt5 = isinstance(gateway, MT5DemoGateway)
    startup_by_id = {position.position_id: position for position in startup_positions}
    ledger_ids = {entry.position_id for entry in ledger_open}

    if startup_query_succeeded:
        emit_position_snapshot(startup_positions, datetime.now(timezone.utc))
        for entry in ledger_open:
            sp = startup_by_id.get(entry.position_id)
            if sp is None:
                closed_at = datetime.now(timezone.utc)
                close_reconciliation = _MT5CloseReconciliation(
                    "PENDING", "CLOSED_WHILE_OFFLINE"
                )
                if _is_mt5:
                    close_reconciliation = await _reconcile_mt5_close(
                        gateway,
                        entry.position_id,
                        timeout_seconds=settings.live_paper_order_poll_timeout_seconds,
                    )
                position_ledger.mark_closed(
                    broker=broker_name,
                    position_id=entry.position_id,
                    closed_at=close_reconciliation.closed_at or closed_at,
                    close_price=close_reconciliation.exit_price,
                    realized_pnl=close_reconciliation.pnl,
                    currency=account.currency,
                    reconciliation_state=close_reconciliation.state,
                )
                emit("POSITION_CLOSED", closed_at, {
                    "candidate_id": None,
                    "symbol": entry.symbol,
                    "side": "UNKNOWN",
                    "position_id": entry.position_id,
                    "broker_order_id": entry.order_id,
                    "broker_fill_price": close_reconciliation.exit_price,
                    "broker_fill_time": (
                        close_reconciliation.closed_at.isoformat()
                        if close_reconciliation.closed_at else None
                    ),
                    "exit_price": close_reconciliation.exit_price,
                    "pnl": close_reconciliation.pnl,
                    "currency": account.currency,
                    "reconciliation_state": close_reconciliation.state,
                    "exit_reason": close_reconciliation.reason,
                    "closed_while_offline": True,
                    "campaign_mode": "live_paper",
                    "session_kind": "live_paper",
                })
                continue

            _own_order_ids.add(sp.position_id)
            _open_trades[sp.position_id] = {
                "candidate_id": None,
                "symbol": entry.symbol,
                "side": sp.side.value,
                "entry_price": float(sp.open_price),
                "current_price": sp.current_price,
                "stop_loss": sp.stop_loss,
                "take_profit": sp.take_profit,
                "volume": float(sp.volume),
                "opened_at": entry.opened_at,
                "recovered": True,
            }
            emit("POLICY", datetime.now(timezone.utc), {
                "result": "RECOVERED",
                "reason_code": "POSITION_RECOVERED_ON_STARTUP",
                "recovery_source": "LOCAL_POSITION_LEDGER",
                "position_id": sp.position_id,
                "order_id": entry.order_id,
                "symbol": entry.symbol,
                "side": sp.side.value,
                "volume": float(sp.volume),
                "open_price": float(sp.open_price),
                "current_price": sp.current_price,
                "stop_loss": sp.stop_loss,
                "take_profit": sp.take_profit,
                "note": "Ledger-confirmed position; counts toward open-position limits",
            })

        unmatched_positions = [
            position for position in startup_positions
            if position.position_id not in ledger_ids
        ]
        for sp in unmatched_positions:
            if _is_mt5 and sp.magic == LIVE_MAGIC_NUMBER:
                recovered_at = sp.opened_at or datetime.now(timezone.utc)
                position_ledger.record_open(
                    broker=broker_name,
                    symbol=sp.symbol,
                    position_id=sp.position_id,
                    order_id=sp.position_id,
                    opened_at=recovered_at,
                )
                _own_order_ids.add(sp.position_id)
                _open_trades[sp.position_id] = {
                    "candidate_id": None,
                    "symbol": sp.symbol,
                    "side": sp.side.value,
                    "entry_price": float(sp.open_price),
                    "current_price": sp.current_price,
                    "stop_loss": sp.stop_loss,
                    "take_profit": sp.take_profit,
                    "volume": float(sp.volume),
                    "opened_at": recovered_at.isoformat(),
                    "recovered": True,
                }
                emit("POLICY", datetime.now(timezone.utc), {
                    "result": "RECOVERED",
                    "reason_code": "RECOVERED_VIA_MT5_TAG_FALLBACK",
                    "recovery_source": "MT5_MAGIC_FALLBACK",
                    "position_id": sp.position_id,
                    "symbol": sp.symbol,
                    "side": sp.side.value,
                    "volume": float(sp.volume),
                    "open_price": float(sp.open_price),
                    "note": "Ledger row was missing; MT5 magic fallback was persisted",
                })
            elif not _is_mt5:
                emit("POLICY", datetime.now(timezone.utc), {
                    "result": "ATTENTION_REQUIRED",
                    "reason_code": "UNMATCHED_DERIV_POSITION_ON_STARTUP",
                    "position_id": sp.position_id,
                    "symbol": sp.symbol,
                    "side": sp.side.value,
                    "volume": float(sp.volume),
                    "ownership": "UNKNOWN",
                    "action": "Manual review required; position was not modified or counted as campaign-owned",
                })

    candles_processed = 0
    start_monotonic = time.monotonic()
    last_candle_time: datetime | None = None
    stop_reason = "UNKNOWN"

    # 7b. Main loop
    while True:
        now = datetime.now(timezone.utc)

        # Check stop conditions
        if eff_max_candles is not None and candles_processed >= eff_max_candles:
            logger.info("Live-paper campaign reached maximum candle count: {}", candles_processed)
            stop_reason = "MAX_CANDLES"
            break
        if eff_max_duration is not None and (time.monotonic() - start_monotonic) >= eff_max_duration:
            logger.info("Live-paper campaign reached maximum duration: {}s", eff_max_duration)
            stop_reason = "MAX_DURATION"
            break

        # Fetch candles
        candles = await gateway.get_candles(symbol, timeframe, 501)
        if not candles:
            if poll_interval_seconds > 0:
                await asyncio.sleep(poll_interval_seconds)
            continue

        provider_symbol = provider_symbol_for(
            canonical_symbol=symbol,
            source="deriv_public" if broker_name == "deriv_demo" else "mt5",
        )
        observations = closed_observations_from_candles(
            candles=candles,
            canonical_symbol=symbol,
            provider_symbol=provider_symbol,
            source=broker_name,
            timeframe=timeframe,
            observed_at=now,
        )
        if not observations:
            await asyncio.sleep(poll_interval_seconds if poll_interval_seconds > 0 else 0.005)
            continue
        latest_candle_time = observations[-1].candle_opened_at
        if last_candle_time is not None and latest_candle_time <= last_candle_time:
            # No new closed candle yet
            await asyncio.sleep(poll_interval_seconds if poll_interval_seconds > 0 else 0.005)
            continue

        last_candle_time = latest_candle_time
        candles_processed += 1

        window = observations[-500:]
        latest = window[-1]
        emit("OBSERVATION", latest.candle_opened_at, {
            "candles_processed": candles_processed,
            "symbol": symbol,
            "timeframe": timeframe.value,
            "candle_time": latest.candle_opened_at.isoformat(),
        })

        # Strategy evaluation
        signal, facts = await evaluate_strategy_candidate(window)
        facts["strategy_signal_direction"] = facts.get("signal_direction", "NO_TRADE")
        pending_before = confirmation.pending
        transition = confirmation.observe(latest.candle_opened_at, str(facts.get("regime", "UNKNOWN")))
        current_direction = str(signal.get("signal", "NO_TRADE"))
        freshness, expires_at = _signal_freshness(latest, now)
        quality_score = signal.get("confidence", facts.get("signal_confidence"))
        emit("SIGNAL", latest.candle_opened_at, {
            "symbol": symbol,
            "timeframe": timeframe.value,
            "signal_candle": latest.candle_opened_at.isoformat(),
            "direction": current_direction,
            "confidence": facts.get("signal_confidence"),
            "conclusion": current_direction,
            "quality_score": quality_score,
            "observed_at": now.isoformat(),
            "candle_closed_at": latest.closed_at.isoformat(),
            "expires_at": expires_at.isoformat(),
            "data_freshness": freshness,
            "regime": facts.get("regime"),
            "momentum": facts.get("momentum"),
            "volatility": facts.get("volatility"),
            "rsi": facts.get("rsi"),
        })
        await notification_events.live_campaign_signal(
            actionable=current_direction in {"BUY", "SELL"},
            execution_enabled=bool(settings.broker_execution_enabled),
            facts={
                "Symbol / timeframe": f"{symbol} / {timeframe.value}",
                "Conclusion": current_direction,
                "Quality score": str(quality_score if quality_score is not None else "UNAVAILABLE"),
                "Observed at": now.isoformat(),
                "Candle closed at": latest.closed_at.isoformat(),
                "Expires at": expires_at.isoformat(),
                "Data freshness": freshness,
            },
        )
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
            rate_allowed, rate_code = spacing_guard.check_and_record(now)
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
                emit_position_snapshot(broker_positions, now)
            except Exception as exc:
                logger.warning("Failed to retrieve broker positions: {}", exc)
                broker_positions = ()

            broker_pos_ids = {p.position_id for p in broker_positions}
            # Detect local vs broker mismatch
            mismatched = [oid for oid in list(_open_trades.keys()) if oid not in broker_pos_ids]
            for m_id in mismatched:
                trade = _open_trades.pop(m_id)
                emit("POLICY", now, {
                    "result": "MISMATCH",
                    "reason_code": "BROKER_POSITION_MISMATCH",
                    "order_id": m_id,
                    "candidate_id": trade.get("candidate_id"),
                }, trade.get("candidate_id"))
                close_reconciliation = (
                    await _reconcile_mt5_close(
                        gateway,
                        m_id,
                        timeout_seconds=settings.live_paper_order_poll_timeout_seconds,
                    )
                    if _is_mt5
                    else _MT5CloseReconciliation(
                        "PENDING", "POSITION_NO_LONGER_OPEN"
                    )
                )
                position_ledger.mark_closed(
                    broker=broker_name,
                    position_id=m_id,
                    closed_at=close_reconciliation.closed_at or now,
                    close_price=close_reconciliation.exit_price,
                    realized_pnl=close_reconciliation.pnl,
                    currency=account.currency,
                    reconciliation_state=close_reconciliation.state,
                )
                emit("POSITION_CLOSED", now, {
                    "candidate_id": trade.get("candidate_id"),
                    "symbol": trade["symbol"],
                    "side": trade["side"],
                    "position_id": m_id,
                    "broker_order_id": trade.get("order_id", m_id),
                    "broker_fill_price": close_reconciliation.exit_price,
                    "broker_fill_time": (
                        close_reconciliation.closed_at.isoformat()
                        if close_reconciliation.closed_at else None
                    ),
                    "exit_price": close_reconciliation.exit_price,
                    "pnl": close_reconciliation.pnl,
                    "currency": account.currency,
                    "reconciliation_state": close_reconciliation.state,
                    "exit_reason": close_reconciliation.reason,
                    "campaign_mode": "live_paper",
                    "session_kind": "live_paper",
                }, trade.get("candidate_id"))

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

            mt5_risk_facts: Mapping[str, Any] | None = None
            if broker_name == "mt5_demo":
                try:
                    exec_quantity, mt5_risk_facts = await gateway.authorize_account_currency_risk(
                        symbol=symbol,
                        side=side,
                        balance=account.balance,
                        risk_percent=settings.risk_percent,
                        entry=entry_price,
                        stop_loss=stop_loss,
                    )
                except Exception as exc:
                    emit("RISK", now, {
                        "result": "REJECTED",
                        "reason_code": "MT5_ACCOUNT_CURRENCY_RISK_UNVERIFIED",
                        "reason": str(exc),
                        "candidate_id": candidate_id,
                    }, candidate_id)
                    confirmation.save(pending_confirmation_path)
                    continue
                sizing = None
            else:
                sizing = authorize_execution_quantity(
                    broker=broker_name,
                    balance=account.balance,
                    risk_percent=settings.risk_percent,
                    entry=entry_price,
                    stop_loss=stop_loss,
                )

            if sizing is not None and (not sizing.risk_verifiable or sizing.quantity is None):
                emit("RISK", now, {
                    "result": "REJECTED",
                    "reason_code": sizing.reason,
                    "candidate_id": candidate_id,
                }, candidate_id)
                confirmation.save(pending_confirmation_path)
                continue

            if broker_name != "mt5_demo":
                exec_quantity = sizing.quantity

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
                "authorized_risk_amount": str(
                    mt5_risk_facts["authorized_risk_amount"]
                    if mt5_risk_facts is not None else sizing.authorized_risk_amount
                ),
                "expected_loss_at_stop": str(
                    mt5_risk_facts["expected_loss_at_stop"]
                    if mt5_risk_facts is not None else sizing.expected_loss_at_stop
                ),
                "margin_requirement": (
                    str(mt5_risk_facts["margin_requirement"])
                    if mt5_risk_facts is not None else None
                ),
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
                authorized_risk_amount=(
                    float(mt5_risk_facts["authorized_risk_amount"])
                    if mt5_risk_facts is not None else sizing.authorized_risk_amount
                ),
                expected_loss_at_stop=(
                    float(mt5_risk_facts["expected_loss_at_stop"])
                    if mt5_risk_facts is not None else sizing.expected_loss_at_stop
                ),
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
            def consume_lifetime_slot(_decision) -> None:
                nonlocal submissions_started
                # This is the sole order-count authority. It is durable and
                # account-scoped; a process restart cannot restore the slot.
                lifetime_guard.consume(account_identity.scope)
                submissions_started += 1

            try:
                result = await executor.submit(
                    intent,
                    exec_context,
                    before_submit=consume_lifetime_slot,
                )
            except RuntimeError as exc:
                if "lifetime execution cap" not in str(exc):
                    raise
                emit("POLICY", now, {
                    "result": "BLOCKED",
                    "reason_code": "ACCOUNT_LIFETIME_CAP_CONSUMED",
                    "account_scope": account_identity.scope,
                    "candidate_id": candidate_id,
                }, candidate_id)
                confirmation.save(pending_confirmation_path)
                continue

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
                _used_idempotency_keys.add(idempotency_key)

                # Look up fill details
                cur_positions = tuple(await gateway.get_positions())
                matched_pos = next((p for p in cur_positions if p.position_id == order_id), None)
                if matched_pos is None:
                    new_symbol_positions = [
                        p for p in cur_positions
                        if p.position_id not in broker_pos_ids
                        and p.symbol.strip().upper() == symbol.strip().upper()
                    ]
                    if len(new_symbol_positions) == 1:
                        matched_pos = new_symbol_positions[0]
                position_id = matched_pos.position_id if matched_pos is not None else order_id
                pos_price = getattr(matched_pos, "open_price", getattr(matched_pos, "entry_price", None)) if matched_pos else None
                fill_price = float(pos_price) if pos_price is not None else entry_price
                filled_vol = getattr(matched_pos, "volume", exec_quantity.value) if matched_pos else exec_quantity.value
                filled_vol = float(filled_vol) if filled_vol else exec_quantity.value
                is_partial = filled_vol < exec_quantity.value

                # The broker fill necessarily precedes this durable write. A
                # crash in that narrow interval can leave no ledger row; MT5's
                # magic fallback can repair it, while Deriv requires manual
                # review because its portfolio API returns no submission tag.
                position_ledger.record_open(
                    broker=broker_name,
                    symbol=symbol,
                    position_id=position_id,
                    order_id=order_id,
                    opened_at=now,
                )
                _own_order_ids.add(position_id)

                emit("POSITION_OPENED", now, {
                    "candidate_id": candidate_id,
                    "symbol": symbol,
                    "side": side.value,
                    "position_id": position_id,
                    "requested_price": entry_price,
                    "broker_order_id": order_id,
                    "broker_fill_price": fill_price,
                    "broker_fill_time": now.isoformat(),
                    "slippage": abs(fill_price - entry_price),
                    "requested_volume": exec_quantity.value,
                    "filled_volume": filled_vol,
                    "stop_loss": matched_pos.stop_loss if matched_pos else stop_loss,
                    "take_profit": matched_pos.take_profit if matched_pos else take_profit,
                    "partial_fill": is_partial,
                    "campaign_mode": "live_paper",
                    "session_kind": "live_paper",
                }, candidate_id)

                _open_trades[position_id] = {
                    "candidate_id": candidate_id,
                    "symbol": symbol,
                    "side": side.value,
                    "order_id": order_id,
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
            emit_position_snapshot(cur_positions, now)
        except Exception:
            cur_positions = ()

        cur_pos_ids = {p.position_id for p in cur_positions}
        for open_oid in list(_open_trades.keys()):
            if open_oid not in cur_pos_ids:
                trade = _open_trades.pop(open_oid)
                close_reconciliation = (
                    await _reconcile_mt5_close(
                        gateway,
                        open_oid,
                        timeout_seconds=settings.live_paper_order_poll_timeout_seconds,
                    )
                    if _is_mt5
                    else _MT5CloseReconciliation(
                        "PENDING", "POSITION_NO_LONGER_OPEN"
                    )
                )

                position_ledger.mark_closed(
                    broker=broker_name,
                    position_id=open_oid,
                    closed_at=close_reconciliation.closed_at or now,
                    close_price=close_reconciliation.exit_price,
                    realized_pnl=close_reconciliation.pnl,
                    currency=account.currency,
                    reconciliation_state=close_reconciliation.state,
                )
                emit("POSITION_CLOSED", now, {
                    "candidate_id": trade.get("candidate_id"),
                    "symbol": trade["symbol"],
                    "side": trade["side"],
                    "position_id": open_oid,
                    "broker_order_id": trade.get("order_id", open_oid),
                    "broker_fill_price": close_reconciliation.exit_price,
                    "broker_fill_time": (
                        close_reconciliation.closed_at.isoformat()
                        if close_reconciliation.closed_at else None
                    ),
                    "exit_price": close_reconciliation.exit_price,
                    "pnl": close_reconciliation.pnl,
                    "currency": account.currency,
                    "reconciliation_state": close_reconciliation.state,
                    "exit_reason": close_reconciliation.reason,
                    "campaign_mode": "live_paper",
                    "session_kind": "live_paper",
                }, trade.get("candidate_id"))

        if poll_interval_seconds > 0:
            await asyncio.sleep(poll_interval_seconds)

    # 8. Finalize evidence and write summary
    emit("CAMPAIGN_STOPPED", datetime.now(timezone.utc), {
        "stop_reason": stop_reason,
        "candles_processed": candles_processed,
        "orders_submitted": submissions_started,
        "account_scope": account_identity.scope,
    })
    evidence_store.finalize(session_id)

    ended_at = datetime.now(timezone.utc)
    summary: dict[str, Any] = {
        "session": {
            "session_id": session_id,
            "status": "COMPLETED",
            "campaign_mode": "live_paper",
            "broker": broker_name,
            "symbol": symbol,
            "timeframe": timeframe.value,
            "processed_candles": candles_processed,
            "started_at": started_at.isoformat(),
            "ended_at": ended_at.isoformat(),
            "duration_seconds": time.monotonic() - start_monotonic,
            "stop_reason": stop_reason,
            "orders_submitted": submissions_started,
            "account_scope": account_identity.scope,
            "evidence_path": str(evidence_path),
            "position_ledger_path": str(ledger_path),
            "output_path": str(output),
        },
        "live_session_identity": live_identity.payload(),
        "research_fingerprint": fingerprint.payload(),
    }

    temp_path = output.with_suffix(output.suffix + ".tmp")
    temp_path.write_text(json.dumps(summary, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    os.replace(temp_path, output)

    return summary
