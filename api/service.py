"""JQE Application Service Boundary.

Coordinates read-only queries against Quant Core domain services
(BrokerGateway, StrategyEngine, RiskEngine, Performance Analytics).
Encapsulates all domain coordination so the API router remains a thin HTTP layer.
"""

from __future__ import annotations

import datetime
import asyncio
from decimal import Decimal
from dataclasses import asdict
from hashlib import sha256
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pandas as pd

from api.dto import (
    CandleItemDTO,
    CandlesResponse,
    ConfidenceBreakdownDTO,
    ExecutionStateResponse,
    LiveExecutionResponse,
    ExecutionSafetyResponse,
    RecoveryDiagnosticsResponse,
    RecoveryIntentDiagnosticDTO,
    RecoveryQuantityDTO,
    MarketSummaryResponse,
    PerformanceSummaryResponse,
    PositionDTO,
    RiskStatusResponse,
    SignalResponse,
    SystemStatusResponse,
    PaperRuntimeStatusResponse,
    TradeHistoryDTO,
    TradePlanDTO,
    MarketSetup,
    PaperExecutionOutcomeDTO,
    DataFreshnessDTO,
    SetupAuthorizationDTO,
    SetupEvidenceDTO,
    ActiveMarketAnalysisResponse,
    OfflineMonitoringResponse,
    MonitoringGateDTO,
    SimulationSubmissionTelemetryDTO,
    BrokerItemStatusDTO,
    ActiveBrokerIdentityDTO,
    BrokerStatusResponse,
    SelectBrokerResponse,
    WatchlistCapUsageDTO,
    WatchlistCapUsageResponse,
)
from broker.base import BrokerGateway
from broker.demo_guard import DEFAULT_BROKER_EVIDENCE_PATH
from broker.factory import get_gateway
from broker.deriv_public_data import DerivPublicMarketData
from broker.simulation_gateway import SimulationGateway
from broker.types import ExecutionQuantity, ExecutionQuantityUnit, OrderSide, Timeframe, TIMEFRAME_SECONDS
from config.settings import settings
from core.data_validator import validate_market_data
from core.exceptions import MarketDataError
from core.indicators import calculate_indicators
from core.regime import detect_regime
from data.broker_selection import BrokerSelectionStore, normalize_broker_name
from data.watchlist import WatchlistStore
from execution.daily_instrument_guard import DailyInstrumentTradeGuard
from execution.safety import RiskEvaluationState, SQLiteExecutionSafetyStore, utc_now
from execution.persistence import SQLiteIntentRecordStore
from execution.paper_runtime import PaperRuntimeStateStore
from execution.dashboard_paper import DashboardPaperGateway, DashboardPaperStore
from execution.simulation_daily_guard import (
    DEMO_DAILY_SUBMISSION_CAP_REACHED,
    SQLiteSimulationDailySubmissionGuard,
    SimulationDailyCapReached,
)
from execution.executor import AsyncTradeExecutor, ReconciliationState
from execution.policy import ExecutionContext, ExecutionIntent, ExecutionPolicy, PositionSnapshot
from risk.risk_engine import MIN_CONFIDENCE, RiskEngine
from strategy.strategy_engine import StrategyEngine
from strategy.pipeline import generate_trading_signal
from data.historical import CandleDataSource, HistoricalDataService
from data.storage import CandleStore
from data.active_market import (
    ActiveMarketContext,
    candle_close_time,
    freshness_facts,
    fully_closed_candles,
    symbol_display_name,
)
from intelligence.analyst import explain_setup
from execution.market_setup import MarketLevelDTO, resolve_historical_win_rate
from monitoring.offline_analysis import run_offline_analysis as build_offline_analysis
from research.current_research_status import current_research_status

_TIMEFRAME_MAP: dict[str, Timeframe] = {tf.value: tf for tf in Timeframe}
_DERIV_PUBLIC_SYMBOLS = {"XAUUSD": "frxXAUUSD"}
_OFFLINE_SIMULATION_SCOPE = "simulation:JQE-DASHBOARD-PAPER"
_MT5_GATEWAY_LOCK = asyncio.Lock()


def _uses_mt5_session() -> bool:
    """Whether API broker work must serialize the process-global MT5 terminal."""
    return settings.effective_broker in {"mt5", "mt5_demo", "weltrade", "weltrade_demo"}


class BrokerSwitchConflictError(RuntimeError):
    """Broker switching is blocked by unresolved durable execution intents."""


class BrokerUnavailableError(RuntimeError):
    """The requested real broker is not configured or not demo-safe; selection refused."""


def _resolve_timeframe(timeframe_str: str | None) -> Timeframe:
    """Resolve timeframe strictly without silent fallback to M5 when requested."""
    if timeframe_str is None or not str(timeframe_str).strip():
        default_tf = settings.default_timeframe.strip().upper()
        if default_tf in _TIMEFRAME_MAP:
            return _TIMEFRAME_MAP[default_tf]
        return Timeframe.H1
    clean = str(timeframe_str).strip().upper()
    if clean in _TIMEFRAME_MAP:
        return _TIMEFRAME_MAP[clean]
    raise MarketDataError(
        f"Unsupported timeframe '{timeframe_str}'. Supported timeframes: {list(_TIMEFRAME_MAP.keys())}"
    )


def _price_decimals(symbol: str) -> int:
    """Return backend-owned display precision for a normalized symbol."""
    normalized = symbol.upper()
    if normalized.endswith("JPY"):
        return 3
    if any(asset in normalized for asset in ("BTC", "XAU", "XAG")):
        return 2
    return 5


def _maximum_realized_drawdown(profits: list[float]) -> float:
    """Calculate peak-to-trough cumulative realized P&L without fake equity."""
    cumulative = 0.0
    peak = 0.0
    maximum = 0.0
    for profit in profits:
        cumulative += profit
        peak = max(peak, cumulative)
        maximum = max(maximum, peak - cumulative)
    return round(maximum, 2)


class ApplicationService:
    """Application service for read-only quantitative dashboard and observability."""

    def __init__(
        self,
        gateway: BrokerGateway | None = None,
        market_data_source: CandleDataSource | None = None,
        strategy_engine: StrategyEngine | None = None,
        risk_engine: RiskEngine | None = None,
        candle_store: CandleStore | None = None,
    ) -> None:
        self._gateway = gateway
        self._market_data_source = market_data_source
        self.strategy_engine = strategy_engine or StrategyEngine()
        self.risk_engine = risk_engine or RiskEngine()
        self._candle_store = candle_store or CandleStore(settings.historical_data_path)
        self._pinned_market_batch: tuple[str, Timeframe, list[Any], str, str] | None = None

    def _get_gateway(self) -> BrokerGateway:
        if self._gateway is not None:
            return self._gateway
        return get_gateway(settings)

    def _get_market_data_source(self) -> tuple[CandleDataSource, str]:
        """Resolve telemetry independently from the execution gateway."""
        if self._market_data_source is not None:
            if isinstance(self._market_data_source, DerivPublicMarketData):
                return self._market_data_source, "DERIV_PUBLIC"
            if isinstance(self._market_data_source, SimulationGateway):
                return self._market_data_source, "SIMULATION"
            return self._market_data_source, "UNAVAILABLE"
        if settings.market_data_source == "deriv_public":
            return DerivPublicMarketData(
                app_id=settings.deriv_app_id, endpoint=settings.deriv_public_endpoint
            ), "DERIV_PUBLIC"
        if settings.market_data_source == "broker":
            return self._get_gateway(), "BROKER"
        if isinstance(self._gateway, SimulationGateway):
            return self._gateway, "SIMULATION"
        return SimulationGateway(starting_balance=settings.account_balance), "SIMULATION"

    @asynccontextmanager
    async def _market_source(self):
        source, provenance = self._get_market_data_source()
        connect = getattr(source, "connect", None)
        disconnect = getattr(source, "disconnect", None)
        if _uses_mt5_session():
            async with _MT5_GATEWAY_LOCK:
                if connect is not None:
                    await connect()
                try:
                    yield source, provenance
                finally:
                    if disconnect is not None:
                        await disconnect()
            return
        if connect is not None:
            await connect()
        try:
            yield source, provenance
        finally:
            if disconnect is not None:
                await disconnect()

    @asynccontextmanager
    async def _connected_source(self, source: Any):
        """Connect a broker source while serializing MT5's process-global SDK."""
        connect = getattr(source, "connect", None)
        disconnect = getattr(source, "disconnect", None)
        if _uses_mt5_session():
            async with _MT5_GATEWAY_LOCK:
                if connect is not None:
                    await connect()
                try:
                    yield source
                finally:
                    if disconnect is not None:
                        await disconnect()
            return
        if connect is not None:
            await connect()
        try:
            yield source
        finally:
            if disconnect is not None:
                await disconnect()

    @asynccontextmanager
    async def _gateway_session(self):
        """Yield a connected gateway with the correct broker session guard."""
        async with self._connected_source(self._get_gateway()) as gateway:
            yield gateway

    @staticmethod
    def _provider_symbol(symbol: str, provenance: str) -> str:
        if provenance == "DERIV_PUBLIC":
            return _DERIV_PUBLIC_SYMBOLS.get(symbol.upper(), symbol)
        return symbol

    @staticmethod
    def _provenance(configured: str, candles: list[Any]) -> str:
        if configured != "UNAVAILABLE":
            return configured
        sources = {str(c.source).lower() for c in candles}
        if sources == {"simulation"}:
            return "SIMULATION"
        if sources in ({"deriv"}, {"deriv_public"}):
            return "DERIV_PUBLIC"
        return "UNAVAILABLE"

    async def _get_market_candle_data(
        self, symbol: str, timeframe: Timeframe, count: int
    ) -> tuple[list[Any], str, str, str]:
        """Return provider candles via HistoricalDataService, or truthful cache metadata.

        Returns: (candles, provenance, data_status, cache_status)
        """
        if self._pinned_market_batch is not None:
            pinned_symbol, pinned_timeframe, candles, provenance, status = self._pinned_market_batch
            if pinned_symbol == symbol and pinned_timeframe is timeframe:
                cache_st = "FRESH_CACHE" if status == "CACHED" else "REFRESHED"
                return candles[-count:], provenance, status, cache_st

        # Explicitly injected sources are test/application boundaries and retain
        # their original fail-fast behavior.  They must not silently consume an
        # unrelated on-disk cache partition after a provider failure.
        if self._market_data_source is not None:
            async with self._market_source() as (source, configured):
                candles = await source.get_candles(
                    symbol=self._provider_symbol(symbol, configured),
                    timeframe=timeframe,
                    count=count,
                )
            return candles, self._provenance(configured, candles), "CURRENT", "REFRESHED"

        source, configured = self._get_market_data_source()

        # Synthetic data is generated for the observation instant.  Reading it
        # back from a durable cache can mix independent seeded runs and can make
        # old/future test fixtures look authoritative, so simulation telemetry
        # deliberately bypasses the real-provider cache fallback.
        if configured == "SIMULATION":
            async with self._connected_source(source):
                candles = await source.get_candles(symbol, timeframe, count)
            return candles, "SIMULATION", "CURRENT", "REFRESHED"

        provider = {
            "DERIV_PUBLIC": "deriv",
            "BROKER": "broker",
        }.get(configured, "simulation")
        provider_symbol = self._provider_symbol(symbol, configured)
        historical_service = HistoricalDataService(gateway=source, store=self._candle_store)

        try:
            async with self._connected_source(source):
                candles, downloaded = await historical_service.refresh_latest(
                    symbol=symbol,
                    provider_symbol=provider_symbol,
                    provider=provider,
                    timeframe=timeframe,
                    count=count,
                )

            if candles:
                provenance = self._provenance(configured, candles)
                cache_status = "REFRESHED" if downloaded > 0 else "FRESH_CACHE"
                return candles, provenance, "CURRENT", cache_status
        except Exception:
            pass

        cached = self._candle_store.load_latest(
            symbol, timeframe, count, provider=provider
        )
        if cached:
            cached_df = pd.DataFrame([c.model_dump() for c in cached])
            ordered = all(
                current.time > previous.time
                for previous, current in zip(cached, cached[1:])
            )
            if ordered and validate_market_data(cached_df):
                return cached, configured, "CACHED", "CACHE_ONLY"

        return [], "UNAVAILABLE", "UNAVAILABLE", "EMPTY"

    async def get_market_summary(
        self,
        symbol: str | None = None,
        timeframe_str: str | None = None,
        count: int | None = None,
    ) -> MarketSummaryResponse:
        """Retrieves latest market data and computes key indicators."""
        target_symbol = symbol.strip().upper() if isinstance(symbol, str) and symbol.strip() else settings.default_symbol
        tf = _resolve_timeframe(timeframe_str)
        candle_count = count if isinstance(count, int) and count > 0 else settings.default_candle_count

        candles, provenance, data_status, _cache_status = await self._get_market_candle_data(
            target_symbol, tf, candle_count
        )
        if not candles:
            raise MarketDataError("Market data unavailable", symbol=target_symbol)

        df = pd.DataFrame([c.model_dump() for c in candles])
        if not validate_market_data(df):
            raise MarketDataError("Market data failed validation", symbol=target_symbol)

        df = calculate_indicators(df)
        latest = df.iloc[-1]
        timestamp = (
            latest["time"].isoformat()
            if hasattr(latest.get("time"), "isoformat")
            else str(latest.get("time", ""))
        )

        return MarketSummaryResponse(
            symbol=target_symbol,
            timeframe=tf.value,
            latest_close=float(latest["close"]),
            latest_high=float(latest["high"]),
            latest_low=float(latest["low"]),
            latest_open=float(latest["open"]),
            spread=float(latest["spread"]) if "spread" in latest and pd.notna(latest["spread"]) else None,
            atr=float(latest["ATR"]) if "ATR" in latest and pd.notna(latest["ATR"]) else None,
            rsi=float(latest["RSI"]) if "RSI" in latest and pd.notna(latest["RSI"]) else None,
            ema50=float(latest["EMA50"]) if "EMA50" in latest and pd.notna(latest["EMA50"]) else None,
            ema200=float(latest["EMA200"]) if "EMA200" in latest and pd.notna(latest["EMA200"]) else None,
            timestamp=timestamp,
            price_decimals=_price_decimals(target_symbol),
            market_data_source=provenance,
            market_data_status=data_status,
            stale=data_status == "CACHED",
            degraded=data_status != "CURRENT",
        )

    async def get_market_candles(
        self,
        symbol: str | None = None,
        timeframe_str: str | None = None,
        count: int = 50,
    ) -> CandlesResponse:
        """Retrieves recent candles with computed indicators for charting."""
        target_symbol = symbol.strip().upper() if isinstance(symbol, str) and symbol.strip() else settings.default_symbol
        tf = _resolve_timeframe(timeframe_str)
        candle_count = count if isinstance(count, int) and count > 0 else 50

        candles, provenance, data_status, _cache_status = await self._get_market_candle_data(
            target_symbol, tf, candle_count
        )

        if not candles:
            return CandlesResponse(
                symbol=target_symbol,
                timeframe=tf.value,
                count=0,
                candles=[],
                price_decimals=_price_decimals(target_symbol),
                market_data_source=provenance,
                market_data_status=data_status,
                stale=False,
                degraded=True,
            )

        df = pd.DataFrame([c.model_dump() for c in candles])
        df = calculate_indicators(df)

        candle_items: list[CandleItemDTO] = []
        for _, row in df.iterrows():
            t_str = (
                row["time"].isoformat()
                if hasattr(row.get("time"), "isoformat")
                else str(row.get("time", ""))
            )
            candle_items.append(
                CandleItemDTO(
                    time=t_str,
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row["volume"]) if "volume" in row and pd.notna(row["volume"]) else None,
                    EMA50=float(row["EMA50"]) if "EMA50" in row and pd.notna(row["EMA50"]) else None,
                    EMA200=float(row["EMA200"]) if "EMA200" in row and pd.notna(row["EMA200"]) else None,
                    RSI=float(row["RSI"]) if "RSI" in row and pd.notna(row["RSI"]) else None,
                    ATR=float(row["ATR"]) if "ATR" in row and pd.notna(row["ATR"]) else None,
                )
            )

        return CandlesResponse(
            symbol=target_symbol,
            timeframe=tf.value,
            count=len(candle_items),
            candles=candle_items,
            price_decimals=_price_decimals(target_symbol),
            market_data_source=provenance,
            market_data_status=data_status,
            stale=data_status == "CACHED",
            degraded=data_status != "CURRENT",
        )

    async def get_strategy_signal(
        self,
        symbol: str | None = None,
        timeframe_str: str | None = None,
        count: int | None = None,
    ) -> SignalResponse:
        """Evaluates current market data through the canonical StrategyEngine."""
        target_symbol = symbol.strip().upper() if isinstance(symbol, str) and symbol.strip() else settings.default_symbol
        tf = _resolve_timeframe(timeframe_str)
        candle_count = count if isinstance(count, int) and count > 0 else settings.default_candle_count

        candles, _provenance, _data_status, _cache_status = await self._get_market_candle_data(
            target_symbol, tf, candle_count
        )

        if not candles:
            raise MarketDataError("Market data unavailable", symbol=target_symbol)

        df = pd.DataFrame([c.model_dump() for c in candles])
        if not validate_market_data(df):
            raise MarketDataError("Market data failed validation", symbol=target_symbol)

        df = calculate_indicators(df)
        regime = detect_regime(df)

        decision = generate_trading_signal(
            df, symbol=target_symbol, regime=regime, engine=self.strategy_engine,
            include_details=True,
        )
        intel = decision["intelligence"]

        # Map Breakdown DTO
        breakdown_dto: ConfidenceBreakdownDTO | None = None
        if decision["confidence_breakdown"]:
            cb = decision["confidence_breakdown"]
            breakdown_dto = ConfidenceBreakdownDTO(
                trend_score=cb.trend_score,
                structure_score=cb.structure_score,
                liquidity_score=cb.liquidity_score,
                momentum_score=cb.momentum_score,
                volatility_score=cb.volatility_score,
                risk_score=cb.risk_score,
                total=cb.total,
                factors=cb.factors,
            )

        # Map TradePlan DTO
        plan_dto: TradePlanDTO | None = None
        if decision["trade_plan"]:
            tp = decision["trade_plan"]
            plan_dto = TradePlanDTO(
                symbol=tp.symbol,
                signal=tp.signal,
                confidence=tp.confidence,
                quality=tp.quality,
                score=tp.score,
                setup_type=tp.setup_type,
                entry=tp.entry,
                stop_loss=tp.stop_loss,
                take_profit=tp.take_profit,
                risk_reward=tp.risk_reward,
                risk_percent=tp.risk_percent,
                risk_amount=tp.risk_amount,
                invalidation=tp.invalidation,
                warnings=tp.warnings,
                reasons=tp.reasons,
                is_valid=tp.is_valid(),
            )

        return SignalResponse(
            symbol=target_symbol,
            signal=decision["signal"],
            confidence=decision["confidence"],
            quality=decision["quality"],
            score=decision["score"],
            reasons=decision["reasons"],
            regime=str(intel.get("regime", "UNKNOWN")),
            trend=str(intel.get("trend", "UNKNOWN")),
            momentum=str(intel.get("momentum", "UNKNOWN")),
            volatility=str(intel.get("volatility", "UNKNOWN")),
            liquidity=str(intel.get("liquidity", "UNKNOWN")),
            confidence_breakdown=breakdown_dto,
            trade_plan=plan_dto,
            generated_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            price_decimals=_price_decimals(target_symbol),
        )

    @staticmethod
    def _paper_store() -> DashboardPaperStore:
        return DashboardPaperStore(settings.dashboard_paper_store_path)

    def _paper_context(
        self,
        *,
        symbol: str,
        setup_id: str,
        store: DashboardPaperStore,
        now: datetime.datetime,
    ) -> ExecutionContext:
        positions = tuple(
            PositionSnapshot(symbol=item.symbol, side=item.side)
            for item in store.open_positions()
        )
        daily_trades, realized_loss = store.daily_counts(now)
        balance = Decimal(str(settings.account_balance))
        loss_percent = (
            realized_loss * Decimal("100") / balance if balance > 0 else Decimal("100")
        )
        emergency_value = getattr(settings.emergency_stop, "value", str(settings.emergency_stop))
        emergency_stop = True if emergency_value == "ACTIVE" else False if emergency_value == "CLEAR" else None
        return ExecutionContext(
            emergency_stop=emergency_stop,
            daily_loss_percent=float(loss_percent),
            max_daily_loss_percent=self.risk_engine.max_daily_loss,
            daily_trade_count=daily_trades,
            max_daily_trades=self.risk_engine.max_trades_daily,
            open_positions=positions,
            max_open_positions=1,
            used_idempotency_keys=frozenset({setup_id}) if store.get_outcome(setup_id) else frozenset(),
            execution_enabled=True,
            dry_run=False,
            broker="simulation",
            environment="paper",
            account_id="JQE-DASHBOARD-PAPER",
            approved_brokers=frozenset({"simulation"}),
            approved_environments=frozenset({"paper"}),
            approved_accounts=frozenset({"JQE-DASHBOARD-PAPER"}),
            approved_symbols=frozenset({symbol.upper()}),
            daily_state_authoritative=True,
        )

    async def get_market_setup(
        self,
        symbol: str | None = None,
        timeframe_str: str | None = None,
        count: int | None = None,
    ) -> MarketSetup:
        """Build one closed-candle setup through strategy, risk, and policy."""
        target_symbol = symbol.strip().upper() if isinstance(symbol, str) and symbol.strip() else settings.default_symbol
        tf = _resolve_timeframe(timeframe_str)
        candle_count = count if isinstance(count, int) and count > 0 else settings.default_candle_count
        candles, provenance, data_status, _cache_status = await self._get_market_candle_data(
            target_symbol, tf, candle_count
        )
        if not candles:
            raise MarketDataError("Market data unavailable", symbol=target_symbol)
        df = pd.DataFrame([c.model_dump() for c in candles])
        if not validate_market_data(df):
            raise MarketDataError("Market data failed validation", symbol=target_symbol)
        df = calculate_indicators(df)
        regime = detect_regime(df)
        decision = generate_trading_signal(
            df, symbol=target_symbol, regime=regime, engine=self.strategy_engine,
            include_details=True,
        )
        now = utc_now()
        closed = fully_closed_candles(candles, tf, now)
        latest_closed, expected_closed, freshness_age, freshness_state, freshness_reasons = freshness_facts(
            candles,
            symbol=target_symbol,
            timeframe=tf,
            observed_at=now,
            cache_only=(data_status == "CACHED"),
            continuous_market=True if provenance == "SIMULATION" else None,
        )
        analyzed_candle = closed[-1] if closed else candles[-1]
        analyzed_candle_time = (
            analyzed_candle.time
            if analyzed_candle.time.tzinfo is not None
            else analyzed_candle.time.replace(tzinfo=datetime.timezone.utc)
        )
        close_time = candle_close_time(analyzed_candle, tf)
        forming = close_time > now
        maximum_age = TIMEFRAME_SECONDS[tf] * 2
        expired = freshness_state == "STALE" or (
            freshness_age is not None and freshness_age > Decimal(maximum_age)
        )
        freshness_status = (
            "CACHED" if data_status == "CACHED" else
            "STALE" if expired else
            "CURRENT"
        )
        freshness_reason = (
            "Provider data is cached and cannot authorize a new paper entry"
            if data_status == "CACHED" else
            "Latest candle has not closed" if forming else
            "Latest closed candle exceeded the setup freshness window" if expired else
            "Latest provider candle is closed and within the freshness window"
        )
        plan = decision.get("trade_plan")
        breakdown = decision.get("confidence_breakdown")
        confidence_score = breakdown.total if breakdown is not None else 0
        max_scores = {
            "trend": 25, "structure": 20, "liquidity": 20,
            "momentum": 15, "volatility": 10, "risk": 10,
        }
        evidence = []
        if breakdown is not None:
            for factor, maximum in max_scores.items():
                evidence.append(SetupEvidenceDTO(
                    factor=factor,
                    assessment=breakdown.factors.get(factor, "UNKNOWN"),
                    score=getattr(breakdown, f"{factor}_score"),
                    maximum_score=maximum,
                ))
        direction = decision["signal"]
        reason_codes: list[str] = []
        conflicts = list(dict.fromkeys([
            *decision.get("reasons", []),
            *(plan.warnings if plan is not None else []),
        ]))

        # Calculate structure levels (20-candle lookback on closed candles)
        levels: list[MarketLevelDTO] = []
        if len(df) >= 20:
            recent = df.tail(20)
            low_20 = round(float(recent["low"].min()), _price_decimals(target_symbol))
            high_20 = round(float(recent["high"].max()), _price_decimals(target_symbol))
            levels.append(MarketLevelDTO(kind="SUPPORT", price=Decimal(str(low_20)), method="RECENT_RANGE_20_V1"))
            levels.append(MarketLevelDTO(kind="RESISTANCE", price=Decimal(str(high_20)), method="RECENT_RANGE_20_V1"))

        entry = Decimal(str(plan.entry)) if plan is not None and plan.entry is not None else None
        stop = Decimal(str(plan.stop_loss)) if plan is not None and plan.stop_loss is not None else None
        targets = [Decimal(str(plan.take_profit))] if plan is not None and plan.take_profit is not None else []
        rr = Decimal(str(plan.risk_reward)) if plan is not None and plan.risk_reward is not None else None
        blocked_reason = ""
        if direction == "NO_TRADE":
            reason_codes.append("NO_TRADE")
            blocked_reason = "Strategy produced a normal no-trade decision"
            entry = None
            stop = None
            targets = []
            rr = None
        elif plan is None or not plan.is_valid():
            reason_codes.append("INVALID_TRADE_PLAN")
            blocked_reason = "Trade-plan invariants did not pass"
        elif forming:
            reason_codes.append("CANDLE_FORMING")
            blocked_reason = freshness_reason
        elif data_status == "CACHED" or expired:
            reason_codes.append("DATA_NOT_FRESH")
            blocked_reason = freshness_reason

        risk_auth = SetupAuthorizationDTO(
            status="BLOCKED" if blocked_reason else "NOT_EVALUATED",
            reason=blocked_reason or "Risk evaluation pending",
            reason_codes=reason_codes.copy(),
        )
        intent: ExecutionIntent | None = None
        store = self._paper_store()
        setup_material = f"1|{target_symbol.upper()}|{tf.value}|{close_time.isoformat()}"
        setup_id = sha256(setup_material.encode("utf-8")).hexdigest()[:24]
        context = self._paper_context(
            symbol=target_symbol, setup_id=setup_id, store=store, now=now
        )
        if not blocked_reason and plan is not None and entry is not None and stop is not None and targets:
            risk = self.risk_engine.approve_trade(
                decision, df, balance=settings.account_balance, enforce_limits=False
            )
            if risk.get("approved") is not True:
                reason_codes.append("RISK_REJECTED")
                blocked_reason = str(risk.get("reason") or "Risk rejected the setup")
                risk_auth = SetupAuthorizationDTO(
                    status="BLOCKED", reason=blocked_reason,
                    reason_codes=["RISK_REJECTED"],
                )
            else:
                sizing = self.risk_engine.authorize_execution_quantity(
                    broker="simulation", balance=settings.account_balance,
                    risk_percent=risk["risk_percent"], entry=float(entry), stop_loss=float(stop),
                )
                if not sizing.risk_verifiable or sizing.quantity is None or sizing.expected_loss_at_stop is None:
                    reason_codes.append("QUANTITY_NOT_VERIFIABLE")
                    blocked_reason = sizing.reason
                    risk_auth = SetupAuthorizationDTO(
                        status="BLOCKED", reason=sizing.reason,
                        reason_codes=["QUANTITY_NOT_VERIFIABLE"],
                    )
                else:
                    risk_auth = SetupAuthorizationDTO(
                        status="AUTHORIZED", reason=risk["reason"], reason_codes=["RISK_AUTHORIZED"],
                        authorized_risk_amount=Decimal(str(sizing.authorized_risk_amount)),
                        authorized_risk_percent=Decimal(str(risk["risk_percent"])),
                        quantity=Decimal(str(sizing.quantity.value)),
                        quantity_unit=sizing.quantity.unit.value,
                        expected_loss_at_stop=Decimal(str(sizing.expected_loss_at_stop)),
                    )
                    intent = ExecutionIntent(
                        symbol=target_symbol, side=OrderSide(direction), quantity=sizing.quantity,
                        authorized_risk_amount=sizing.authorized_risk_amount,
                        expected_loss_at_stop=sizing.expected_loss_at_stop,
                        quantity_risk_verified=True, entry=float(entry), stop_loss=float(stop),
                        take_profit=float(targets[0]), idempotency_key=setup_id, risk_approved=True,
                    )

        policy = ExecutionPolicy.evaluate(intent, context) if intent is not None else None
        if policy is not None and not policy.allowed:
            reason_codes.append(policy.code.value)
            blocked_reason = policy.reason
        execution_auth = SetupAuthorizationDTO(
            status="AUTHORIZED" if policy is not None and policy.allowed else "BLOCKED",
            reason=policy.reason if policy is not None else blocked_reason or "No executable direction",
            reason_codes=[policy.code.value] if policy is not None else reason_codes.copy(),
            authorized_risk_amount=risk_auth.authorized_risk_amount if policy is not None and policy.allowed else None,
            authorized_risk_percent=risk_auth.authorized_risk_percent if policy is not None and policy.allowed else None,
            quantity=risk_auth.quantity if policy is not None and policy.allowed else None,
            quantity_unit=risk_auth.quantity_unit if policy is not None and policy.allowed else None,
            expected_loss_at_stop=risk_auth.expected_loss_at_stop if policy is not None and policy.allowed else None,
        )
        state = "FORMING" if forming else "EXPIRED" if expired else "READY" if execution_auth.status == "AUTHORIZED" else "BLOCKED"
        historical_win_rate = resolve_historical_win_rate(target_symbol, tf.value)
        data_freshness = DataFreshnessDTO(
            status=freshness_status,
            source=provenance,
            age_seconds=freshness_age,
            maximum_age_seconds=maximum_age,
            reason=freshness_reason,
            latest_closed_candle_at=latest_closed,
            expected_closed_candle_at=expected_closed,
            freshness_tolerance_seconds=TIMEFRAME_SECONDS[tf],
            freshness_age_seconds=freshness_age,
            freshness_state=freshness_state,
            freshness_reason_codes=freshness_reasons,
            reason_codes=freshness_reasons.copy(),
        )
        setup = MarketSetup(
            setup_id=setup_id, symbol=target_symbol, timeframe=tf.value,
            observed_at=now, candle_close_time=close_time,
            expires_at=close_time + datetime.timedelta(seconds=maximum_age),
            direction=direction,
            setup_state=state, entry_price=entry, stop_loss=stop, targets=targets,
            levels=levels, analyzed_candle_time=analyzed_candle_time,
            risk_reward_ratio=rr, confidence_score=confidence_score,
            confidence_method="JQE_DETERMINISTIC_6_FACTOR_V1",
            evidence=evidence, conflicts=conflicts, market_regime=str(decision["intelligence"].get("regime", "UNKNOWN")),
            invalidation_condition=plan.invalidation if plan is not None else None,
            data_freshness=data_freshness,
            risk_authorization=risk_auth, execution_authorization=execution_auth,
            reason_codes=list(dict.fromkeys(reason_codes)),
            historical_win_rate=historical_win_rate,
        )
        setup.explanation = explain_setup(setup)
        store.save_setup(setup)
        return setup

    async def get_active_market_analysis(
        self,
        symbol: str | None = None,
        timeframe_str: str | None = None,
        count: int | None = None,
    ) -> ActiveMarketAnalysisResponse:
        """Single authoritative entry point for active-market state, setup, and explanation."""
        target_symbol = symbol.strip().upper() if isinstance(symbol, str) and symbol.strip() else settings.default_symbol
        tf = _resolve_timeframe(timeframe_str)
        candle_count = count if isinstance(count, int) and count > 0 else settings.default_candle_count

        candles, provenance, data_status, cache_status = await self._get_market_candle_data(
            target_symbol, tf, candle_count
        )
        if not candles:
            raise MarketDataError("Market data unavailable", symbol=target_symbol)

        # Every projection in this response must describe the exact same candle
        # batch.  This especially matters for the synthetic source, which creates
        # a new random-walk batch on every request.
        self._pinned_market_batch = (
            target_symbol,
            tf,
            candles,
            provenance,
            data_status,
        )
        try:
            setup = await self.get_market_setup(target_symbol, tf.value, candle_count)
            summary = await self.get_market_summary(target_symbol, tf.value, candle_count)
            market_candles = await self.get_market_candles(target_symbol, tf.value, candle_count)
            signal = await self.get_strategy_signal(target_symbol, tf.value, candle_count)
        finally:
            self._pinned_market_batch = None

        sync_state = (
            "SYNCHRONIZED" if setup.data_freshness.freshness_state == "FRESH" else
            "FORMING" if setup.setup_state == "FORMING" else
            "STALE" if setup.data_freshness.freshness_state == "STALE" else
            "UNKNOWN"
        )
        context = ActiveMarketContext(
            canonical_symbol=target_symbol,
            provider_symbol=self._provider_symbol(target_symbol, provenance),
            display_name=symbol_display_name(target_symbol),
            selected_timeframe=tf.value,
            timeframe_seconds=TIMEFRAME_SECONDS[tf],
            latest_stored_candle_close=setup.candle_close_time,
            expected_latest_closed_candle=setup.data_freshness.expected_closed_candle_at or setup.candle_close_time,
            market_data_observation_time=setup.observed_at,
            strategy_evaluation_time=setup.observed_at,
            setup_creation_time=setup.observed_at,
            setup_expiry_time=setup.candle_close_time + datetime.timedelta(seconds=TIMEFRAME_SECONDS[tf] * 2),
            data_source=provenance,
            cache_status=cache_status,
            synchronization_state=sync_state,
            reason_codes=setup.reason_codes.copy(),
            latest_closed_candle_at=setup.data_freshness.latest_closed_candle_at,
            expected_closed_candle_at=setup.data_freshness.expected_closed_candle_at or setup.candle_close_time,
            freshness_age_seconds=setup.data_freshness.freshness_age_seconds,
            freshness_tolerance_seconds=setup.data_freshness.freshness_tolerance_seconds or TIMEFRAME_SECONDS[tf],
            freshness_state=setup.data_freshness.freshness_state or "UNKNOWN",
            freshness_reason_codes=setup.data_freshness.freshness_reason_codes,
            schema_version=1,
        )
        explanation = setup.explanation or explain_setup(setup)
        return ActiveMarketAnalysisResponse(
            context=context,
            market=summary,
            candles=market_candles,
            signal=signal,
            setup=setup,
            explanation=explanation,
        )

    async def execute_market_setup(self, setup_id: str) -> PaperExecutionOutcomeDTO:
        """Execute a stored setup through the offline paper boundary only."""
        store = self._paper_store()
        existing = store.get_outcome(setup_id)
        if existing is not None:
            return existing.model_copy(update={
                "status": "ALREADY_RECORDED",
                "message": "This paper setup already has a durable outcome",
            })
        setup = store.get_setup(setup_id)
        if setup is None:
            raise ValueError("Unknown market setup")
        now = utc_now()
        expires_at = setup.expires_at or (
            setup.candle_close_time
            + datetime.timedelta(
                seconds=TIMEFRAME_SECONDS[Timeframe(setup.timeframe)] * 2
            )
        )
        expired = now > expires_at
        if setup.setup_state != "READY" or expired:
            code = "SETUP_EXPIRED" if expired else "SETUP_NOT_READY"
            outcome = PaperExecutionOutcomeDTO(
                outcome_id=f"paper-{setup_id}", setup_id=setup_id, recorded_at=now,
                status="BLOCKED", setup_state="EXPIRED" if expired else "BLOCKED",
                reason_codes=[code], message="Paper execution rejected because the setup is not ready",
            )
            store.record_outcome(setup, outcome)
            return outcome
        auth = setup.execution_authorization
        if auth.quantity is None or auth.quantity_unit != ExecutionQuantityUnit.SIMULATION_UNITS.value:
            raise ValueError("Stored paper authorization is incomplete")
        intent = ExecutionIntent(
            symbol=setup.symbol, side=OrderSide(setup.direction),
            quantity=ExecutionQuantity(value=float(auth.quantity), unit=ExecutionQuantityUnit.SIMULATION_UNITS),
            authorized_risk_amount=float(auth.authorized_risk_amount) if auth.authorized_risk_amount is not None else None,
            expected_loss_at_stop=float(auth.expected_loss_at_stop) if auth.expected_loss_at_stop is not None else None,
            quantity_risk_verified=True, entry=float(setup.entry_price),
            stop_loss=float(setup.stop_loss), take_profit=float(setup.targets[0]),
            idempotency_key=setup.setup_id, risk_approved=True,
        )
        context = self._paper_context(
            symbol=setup.symbol, setup_id=setup.setup_id, store=store, now=now
        )
        guard = SQLiteSimulationDailySubmissionGuard(
            settings.simulation_daily_submission_store_path,
            limit=settings.simulation_daily_submission_limit,
        )
        try:
            guard.assert_available(_OFFLINE_SIMULATION_SCOPE, now=now)
        except SimulationDailyCapReached as exc:
            outcome = PaperExecutionOutcomeDTO(
                outcome_id=f"paper-{setup_id}", setup_id=setup_id, recorded_at=now,
                status="BLOCKED", setup_state="BLOCKED",
                reason_codes=[DEMO_DAILY_SUBMISSION_CAP_REACHED], message=str(exc),
            )
            store.record_outcome(setup, outcome)
            return outcome
        executor = AsyncTradeExecutor(
            DashboardPaperGateway(store, setup, guard, _OFFLINE_SIMULATION_SCOPE),
            SQLiteIntentRecordStore(settings.dashboard_paper_intent_store_path),
        )
        result = await executor.submit(intent, context)
        opened = result.state is ReconciliationState.ALREADY_EXECUTED and result.order_id is not None
        outcome_codes = [result.decision.code.value]
        if not opened and result.decision.allowed:
            outcome_codes = [
                "SIMULATED_BROKER_REJECTED"
                if result.state is ReconciliationState.REJECTED
                else "SIMULATION_SUBMISSION_OUTCOME_UNKNOWN"
            ]
        outcome = PaperExecutionOutcomeDTO(
            outcome_id=f"paper-{setup_id}", setup_id=setup_id, recorded_at=now,
            status="OPENED" if opened else "BLOCKED",
            setup_state="EXECUTED" if opened else "BLOCKED",
            order_id=result.order_id, execution_price=setup.entry_price if opened else None,
            quantity=auth.quantity if opened else None,
            quantity_unit=auth.quantity_unit if opened else None,
            reason_codes=outcome_codes, message=result.reason,
        )
        store.record_outcome(setup, outcome)
        if opened:
            store.save_setup(setup.model_copy(update={"setup_state": "EXECUTED"}))
        return outcome

    def get_offline_monitoring(self) -> OfflineMonitoringResponse:
        """Build a truthful, read-only view from persisted offline state."""
        now = utc_now()
        store = self._paper_store()
        setup = store.latest_setup()
        latest_outcome = store.latest_outcome()
        guard = SQLiteSimulationDailySubmissionGuard(
            settings.simulation_daily_submission_store_path,
            limit=settings.simulation_daily_submission_limit,
        )
        cap = guard.status(_OFFLINE_SIMULATION_SCOPE, now=now)
        cap_codes = [] if cap.available else [DEMO_DAILY_SUBMISSION_CAP_REACHED]
        if setup is None:
            unavailable = MonitoringGateDTO(
                state="UNAVAILABLE", value="NOT OBSERVED", source="OFFLINE_EVIDENCE",
                reason_codes=["NOT_OBSERVED"],
            )
            strategy = candle = risk = authorization = unavailable
        else:
            observed = setup.observed_at.astimezone(datetime.timezone.utc)
            expired = setup.expires_at is not None and now > setup.expires_at
            stale = expired or setup.data_freshness.status in {"CACHED", "STALE", "UNAVAILABLE"}
            freshness_codes = list(dict.fromkeys(
                [*setup.data_freshness.reason_codes, *( ["SETUP_EXPIRED"] if expired else [])]
            ))
            candle = MonitoringGateDTO(
                state="STALE" if stale else "FRESH",
                value=setup.data_freshness.status,
                observed_at=observed.isoformat(), source=setup.data_freshness.source,
                reason_codes=freshness_codes,
            )
            strategy = MonitoringGateDTO(
                state="STALE" if stale else "FRESH",
                value=setup.direction, observed_at=observed.isoformat(),
                source="CANONICAL_STRATEGY_PIPELINE",
                reason_codes=list(setup.reason_codes),
            )
            risk = MonitoringGateDTO(
                state="STALE" if stale else ("BLOCKED" if setup.risk_authorization.status == "BLOCKED" else "FRESH"),
                value=setup.risk_authorization.status, observed_at=observed.isoformat(),
                source="OFFLINE_SETUP", reason_codes=list(setup.risk_authorization.reason_codes),
            )
            authorization = MonitoringGateDTO(
                state="STALE" if stale else ("BLOCKED" if setup.execution_authorization.status != "AUTHORIZED" else "FRESH"),
                value=setup.execution_authorization.status, observed_at=observed.isoformat(),
                source="OFFLINE_SIMULATION_POLICY",
                reason_codes=list(setup.execution_authorization.reason_codes),
            )
            if latest_outcome is not None and latest_outcome.setup_id == setup.setup_id and latest_outcome.status == "BLOCKED":
                authorization = MonitoringGateDTO(
                    state="STALE" if stale else "BLOCKED", value="BLOCKED",
                    observed_at=latest_outcome.recorded_at.astimezone(datetime.timezone.utc).isoformat(),
                    source="OFFLINE_SIMULATION_OUTCOME",
                    reason_codes=list(latest_outcome.reason_codes),
                )
        return OfflineMonitoringResponse(
            observed_at=now.isoformat(), environment=settings.environment,
            backend=MonitoringGateDTO(
                state="LIVE", value="ONLINE", observed_at=now.isoformat(),
                source="FASTAPI", reason_codes=[],
            ),
            strategy=strategy, candle_freshness=candle, risk=risk,
            execution_authorization=authorization,
            simulation_submissions=SimulationSubmissionTelemetryDTO(
                state="FRESH" if cap.available else "BLOCKED",
                account_scope=cap.scope, utc_count=cap.count, limit=cap.limit,
                utc_date=cap.utc_date, reset_at=cap.reset_at.isoformat(),
                reason_codes=cap_codes,
            ),
            broker_execution_enabled=settings.broker_execution_enabled,
            assessment=setup,
            latest_paper_outcome=latest_outcome,
            open_paper_positions=len(store.open_positions()),
            research_status=current_research_status(),
        )

    async def run_offline_analysis(self, symbol: str, timeframe_str: str) -> MarketSetup:
        """Publish an analysis-only setup without resolving an execution gateway."""
        target_symbol = symbol.strip().upper()
        if not target_symbol:
            raise MarketDataError("Offline analysis symbol must be nonblank")
        timeframe = _resolve_timeframe(timeframe_str)
        setup = await build_offline_analysis(
            symbol=target_symbol, timeframe=timeframe,
            seed=settings.offline_analysis_seed,
            count=settings.offline_analysis_candle_count,
        )
        self._paper_store().save_setup(setup)
        return setup

    async def get_risk_status(
        self,
        symbol: str | None = None,
        timeframe_str: str | None = None,
    ) -> RiskStatusResponse:
        """Read the latest durable-cycle risk observation without authorizing risk."""
        del symbol, timeframe_str
        store = SQLiteExecutionSafetyStore(
            settings.execution_safety_store_path, initialize=False
        )
        try:
            snapshot = store.read_risk()
        except Exception:
            return RiskStatusResponse(
                balance=0.0, equity=0.0,
                max_daily_loss=self.risk_engine.max_daily_loss,
                max_trades_daily=self.risk_engine.max_trades_daily,
                risk_allowed=False,
                risk_message="Risk observation unavailable",
                rejection_reason="Persisted risk observation could not be trusted",
                observation_status="UNAVAILABLE",
                observation_reason="Persisted risk observation could not be trusted",
                execution_quantity_reason="Risk observation unavailable",
            )
        if snapshot is None:
            return RiskStatusResponse(
                balance=0.0, equity=0.0,
                max_daily_loss=self.risk_engine.max_daily_loss,
                max_trades_daily=self.risk_engine.max_trades_daily,
                risk_allowed=False,
                risk_message="Risk observation not yet published",
                rejection_reason="Risk observation not yet published",
                observation_status="NOT_OBSERVED",
                observation_reason="Risk observation not yet published",
                execution_quantity_reason="Risk observation not yet published",
            )

        observed_at = snapshot.observed_at.astimezone(datetime.timezone.utc)
        age_seconds = (utc_now() - observed_at).total_seconds()
        common = dict(
            balance=snapshot.balance or 0.0,
            equity=snapshot.equity or 0.0,
            currency=snapshot.currency or "USD",
            max_daily_loss=snapshot.max_daily_loss or 0.0,
            max_trades_daily=snapshot.max_trades_daily or 0,
            daily_trades_count=snapshot.daily_trades_count or 0,
            daily_loss_percent=snapshot.daily_loss_percent or 0.0,
            risk_message=snapshot.risk_message,
            rejection_reason=snapshot.rejection_reason,
            observation_timestamp=observed_at.isoformat(),
            observation_age_seconds=max(0.0, age_seconds),
            recommended_lot_size=0.0,
        )
        if age_seconds < 0:
            return RiskStatusResponse(
                **common,
                risk_allowed=False,
                approved=False,
                observation_status="UNAVAILABLE",
                observation_reason="Observation timestamp is in the future",
                execution_quantity_reason="Risk observation unavailable",
            )
        expected_account_id = None
        active_broker = settings.effective_broker
        if active_broker == "simulation":
            expected_account_id = "SIMULATED"
        elif active_broker == "deriv" and settings.deriv_options_account_id:
            expected_account_id = settings.deriv_options_account_id.strip() or None
        elif active_broker in {"mt5", "weltrade"}:
            observed_account = (snapshot.account_id or "").strip()
            if observed_account and observed_account.upper() != "SIMULATED":
                expected_account_id = observed_account
        context_matches = (
            snapshot.broker == active_broker
            and snapshot.environment == settings.environment
            and expected_account_id is not None
            and snapshot.account_id == expected_account_id
        )
        if snapshot.evaluation_state in (
            RiskEvaluationState.AUTHORIZED, RiskEvaluationState.BLOCKED
        ) and not context_matches:
            return RiskStatusResponse(
                balance=0.0,
                equity=0.0,
                max_daily_loss=self.risk_engine.max_daily_loss,
                max_trades_daily=self.risk_engine.max_trades_daily,
                risk_allowed=False,
                approved=False,
                observation_timestamp=observed_at.isoformat(),
                observation_age_seconds=max(0.0, age_seconds),
                observation_status="CONTEXT_MISMATCH",
                observation_reason="Risk observation does not match the active execution context",
                rejection_reason="Risk observation context mismatch",
                execution_quantity_reason="Risk observation unavailable",
            )
        if age_seconds > settings.risk_observation_freshness_seconds:
            return RiskStatusResponse(
                **common,
                risk_allowed=False,
                approved=False,
                observation_available=True,
                observation_status="STALE",
                observation_reason="Risk observation exceeded the freshness threshold",
                risk_authorized=(snapshot.evaluation_state is RiskEvaluationState.AUTHORIZED),
                authorized_risk_amount=snapshot.authorized_risk_amount,
                authorized_risk_percent=snapshot.authorized_risk_percent,
                execution_quantity_reason="Risk observation is stale",
                risk_percent=snapshot.authorized_risk_percent or 0.0,
            )
        if snapshot.evaluation_state in (
            RiskEvaluationState.NOT_EVALUATED, RiskEvaluationState.UNKNOWN
        ):
            return RiskStatusResponse(
                **common,
                risk_allowed=False,
                approved=False,
                observation_status="UNAVAILABLE",
                observation_reason=snapshot.execution_quantity_reason,
                execution_quantity_reason=snapshot.execution_quantity_reason,
            )
        return RiskStatusResponse(
            **common,
            risk_allowed=bool(snapshot.risk_allowed),
            approved=snapshot.evaluation_state is RiskEvaluationState.AUTHORIZED,
            observation_available=True,
            observation_fresh=True,
            observation_status="FRESH",
            observation_reason="Authoritative durable-cycle observation is fresh",
            risk_authorized=(snapshot.evaluation_state is RiskEvaluationState.AUTHORIZED),
            authorized_risk_amount=snapshot.authorized_risk_amount,
            authorized_risk_percent=snapshot.authorized_risk_percent,
            execution_quantity_available=snapshot.execution_quantity_available,
            execution_quantity_value=snapshot.execution_quantity_value,
            execution_quantity_unit=snapshot.execution_quantity_unit,
            execution_quantity_reason=snapshot.execution_quantity_reason,
            risk_percent=snapshot.authorized_risk_percent or 0.0,
        )

    def get_execution_safety(self) -> ExecutionSafetyResponse:
        """Read the canonical snapshot without broker access or policy evaluation."""
        store = SQLiteExecutionSafetyStore(
            settings.execution_safety_store_path, initialize=False
        )
        try:
            snapshot = store.read()
        except Exception:
            return ExecutionSafetyResponse(
                observation_state="UNAVAILABLE",
                reason_codes=["SNAPSHOT_UNAVAILABLE"],
            )
        if snapshot is None:
            return ExecutionSafetyResponse(
                observation_state="NOT_OBSERVED",
                execution_authorization="NOT_EVALUATED",
                daily_state_authority="NOT_EVALUATED",
                reason_codes=["NOT_EVALUATED"],
            )
        age = utc_now() - snapshot.observed_at.astimezone(datetime.timezone.utc)
        if age.total_seconds() > settings.execution_safety_freshness_seconds:
            return ExecutionSafetyResponse(
                schema_version=snapshot.schema_version,
                observed_at=snapshot.observed_at.astimezone(datetime.timezone.utc).isoformat(),
                observation_state="STALE",
                broker=snapshot.broker,
                environment=snapshot.environment,
                durable_executor_enabled=snapshot.durable_executor_enabled,
                reason_codes=["SNAPSHOT_STALE"],
            )
        return ExecutionSafetyResponse(
            schema_version=snapshot.schema_version,
            observed_at=snapshot.observed_at.astimezone(datetime.timezone.utc).isoformat(),
            observation_state="OBSERVED",
            emergency_stop_state=snapshot.emergency_stop_state.value,
            execution_mode=snapshot.execution_mode.value,
            broker=snapshot.broker,
            environment=snapshot.environment,
            durable_executor_enabled=snapshot.durable_executor_enabled,
            daily_state_authority=snapshot.daily_state_authority.value,
            unresolved_intent_count=snapshot.unresolved_intent_count,
            unresolved_intent_blocked=snapshot.unresolved_intent_blocked,
            execution_authorization=snapshot.execution_authorization.value,
            reason_codes=list(snapshot.reason_codes),
        )

    def get_recovery_diagnostics(self) -> RecoveryDiagnosticsResponse:
        """Read durable recovery diagnostics without broker or reconciliation access."""
        path = Path(settings.intent_store_path).expanduser().resolve()
        if not path.is_file():
            return RecoveryDiagnosticsResponse(
                status="UNKNOWN",
                execution_blocked=True,
                reason="Durable recovery state is unavailable",
            )
        try:
            store = SQLiteIntentRecordStore(path, initialize=False)
            inspections = store.list_unresolved_inspections()
        except Exception:
            return RecoveryDiagnosticsResponse(
                status="UNKNOWN",
                execution_blocked=True,
                reason="Durable recovery state could not be read",
            )
        active_broker = settings.effective_broker
        expected_account = (
            "SIMULATED"
            if active_broker == "simulation"
            else settings.deriv_options_account_id.strip()
            if active_broker == "deriv"
            else ""
        )
        diagnostics: list[RecoveryIntentDiagnosticDTO] = []
        for item in inspections:
            scope_matches = (
                bool(item.broker)
                and item.broker.strip().lower() == active_broker
                and bool(item.account_id)
                and item.account_id.strip() == expected_account
            )
            if not item.reconstruction_valid:
                outcome = "MALFORMED_RECORD"
                classification = "NOT_ATTEMPTED"
                reason = "Persisted intent payload invalid"
            elif not scope_matches:
                outcome = "SCOPE_MISMATCH"
                classification = "NOT_ATTEMPTED"
                reason = "Persisted broker/account scope does not match active scope"
            else:
                outcome = item.recovery_outcome or "NOT_OBSERVED"
                classification = item.reconciliation_state or "NOT_OBSERVED"
                reason = item.recovery_reason or "Startup recovery diagnostic not yet published"
            quantity = (
                RecoveryQuantityDTO(value=item.quantity_value, unit=item.quantity_unit)
                if item.quantity_value is not None and item.quantity_unit is not None
                else None
            )
            diagnostics.append(
                RecoveryIntentDiagnosticDTO(
                    idempotency_key=item.idempotency_key,
                    intent_state=item.status.value,
                    broker=item.broker,
                    account_id=item.account_id,
                    symbol=item.symbol,
                    side=item.side,
                    quantity=quantity,
                    entry=item.entry,
                    stop_loss=item.stop_loss,
                    take_profit=item.take_profit,
                    authorized_risk_amount=item.authorized_risk_amount,
                    expected_loss_at_stop=item.expected_loss_at_stop,
                    order_id=item.order_id,
                    transaction_id=item.transaction_id,
                    created_at=item.created_at,
                    updated_at=item.updated_at,
                    reconstruction_valid=item.reconstruction_valid,
                    recovery_outcome=outcome,
                    reconciliation_classification=classification,
                    blocking_reason=reason,
                )
            )
        if not diagnostics:
            return RecoveryDiagnosticsResponse(
                status="CLEAR",
                execution_blocked=False,
                reason="No unresolved durable execution intents",
            )
        return RecoveryDiagnosticsResponse(
            status="BLOCKED",
            unresolved_intent_count=len(diagnostics),
            execution_blocked=True,
            reason="Execution blocked by unresolved durable intent state",
            intents=diagnostics,
        )

    async def get_execution_state(self) -> ExecutionStateResponse:
        """Retrieves open positions and recent executed trades from the broker."""
        async with self._gateway_session() as gateway:
            is_conn = gateway.is_connected
            positions = await gateway.get_positions()
            history = await gateway.get_trade_history()
            account = await gateway.get_account_info()

        pos_dtos = [
            PositionDTO(
                id=p.id,
                symbol=p.symbol,
                side=p.side.value,
                volume=p.volume,
                open_price=p.open_price,
                current_price=p.current_price,
                stop_loss=p.stop_loss,
                take_profit=p.take_profit,
                profit=p.profit,
                price_decimals=_price_decimals(p.symbol),
            )
            for p in positions
        ]

        trade_dtos = [
            TradeHistoryDTO(
                id=t.trade_id,
                symbol=t.symbol,
                side=t.side.value,
                volume=t.volume,
                open_price=t.open_price,
                close_price=t.close_price,
                profit=t.profit,
                open_time=t.opened_at.isoformat() if hasattr(t.opened_at, "isoformat") else str(t.opened_at),
                close_time=t.closed_at.isoformat() if hasattr(t.closed_at, "isoformat") else str(t.closed_at),
                price_decimals=_price_decimals(t.symbol),
            )
            for t in history
        ]

        return ExecutionStateResponse(
            broker=settings.effective_broker,
            connected=is_conn,
            open_positions_count=len(pos_dtos),
            positions=pos_dtos,
            recent_trades_count=len(trade_dtos),
            recent_trades=trade_dtos,
            currency=account.currency,
        )

    async def execute_live_cycle(self, *, confirmed: bool) -> LiveExecutionResponse:
        """Run one explicitly confirmed cycle through the canonical live path.

        This method deliberately delegates to ``main.run`` instead of creating
        an API-specific gateway or submission path. The engine remains fail
        closed: broker execution must be explicitly enabled, the configured
        gateway must prove a DEMO account, and the normal risk/policy/recovery
        checks must all pass.
        """
        if confirmed is not True:
            raise ValueError("Explicit confirmation is required before a demo order cycle")
        if settings.effective_broker == "simulation":
            raise ValueError("Simulation is analysis-only; select a verified demo broker first")
        if settings.broker_execution_enabled is not True:
            raise ValueError(
                "Broker execution is disabled; set JQE_BROKER_EXECUTION_ENABLED=true to arm demo execution"
            )

        from main import run

        if _uses_mt5_session():
            async with _MT5_GATEWAY_LOCK:
                result = await run()
        else:
            result = await run()
        return LiveExecutionResponse(
            status=result.status,
            broker=result.broker,
            symbol=result.symbol,
            side=result.side,
            order_id=result.order_id,
            decision_code=result.decision_code,
            reason=result.reason,
        )

    async def get_performance_summary(self) -> PerformanceSummaryResponse:
        """Computes statistical performance metrics over closed trade history."""
        async with self._gateway_session() as gateway:
            history = await gateway.get_trade_history()
            account = await gateway.get_account_info()

        if not history:
            return PerformanceSummaryResponse(currency=account.currency)

        trades_list: list[dict[str, Any]] = [{"profit": t.profit} for t in history]
        gross_profit = sum(t["profit"] for t in trades_list if t["profit"] > 0)
        gross_loss = abs(sum(t["profit"] for t in trades_list if t["profit"] < 0))
        net_profit = gross_profit - gross_loss
        winning_trades = sum(1 for t in trades_list if t["profit"] > 0)
        losing_trades = sum(1 for t in trades_list if t["profit"] < 0)
        total_trades = len(trades_list)

        return PerformanceSummaryResponse(
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate_percent=round(winning_trades / total_trades * 100, 2),
            profit_factor=round(gross_profit / gross_loss, 2) if gross_loss else 0.0,
            max_drawdown_amount=_maximum_realized_drawdown([t["profit"] for t in trades_list]),
            max_drawdown_percent=None,
            currency=account.currency,
            average_trade=round(net_profit / total_trades, 2),
            gross_profit=round(gross_profit, 2),
            gross_loss=round(gross_loss, 2),
            net_profit=round(net_profit, 2),
        )

    def get_paper_runtime_status(self) -> PaperRuntimeStatusResponse:
        """Read the durable paper-runtime heartbeat without mutating it."""
        path = Path(settings.paper_runtime_state_path).expanduser().resolve()
        if not path.is_file():
            return PaperRuntimeStatusResponse(
                runtime_mode=settings.runtime_mode, running=False, last_action="NOT_OBSERVED",
                notification_state="DISABLED", shutdown_state="STOPPED",
                paper_execution_enabled=False, broker_execution_enabled=False,
            )
        try:
            heartbeat = PaperRuntimeStateStore(path, initialize=False).read()
            return PaperRuntimeStatusResponse(**asdict(heartbeat))
        except Exception:
            return PaperRuntimeStatusResponse(
                runtime_mode=settings.runtime_mode, running=False, last_action="UNAVAILABLE",
                last_error="RUNTIME_STATE_UNAVAILABLE", notification_state="UNAVAILABLE",
                shutdown_state="UNKNOWN", paper_execution_enabled=False,
                broker_execution_enabled=False,
            )

    async def get_system_status(self) -> SystemStatusResponse:
        """Retrieves system status, broker name, and active settings."""
        async with self._gateway_session() as gateway:
            is_conn = gateway.is_connected
            account = await gateway.get_account_info()
            identity = getattr(gateway, "account_identity", None)
            identity_state = getattr(gateway, "identity_state", None)

        telegram_configured = bool(
            settings.telegram_enabled
            and settings.telegram_bot_token
            and settings.telegram_allowed_chat_id is not None
        )

        return SystemStatusResponse(
            environment=settings.environment,
            broker=settings.effective_broker,
            broker_connected=is_conn,
            default_symbol=settings.default_symbol,
            default_timeframe=settings.default_timeframe,
            min_confidence_threshold=MIN_CONFIDENCE,
            server_time=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            status="ONLINE",
            broker_identity_state=(
                identity_state.value
                if identity_state is not None
                else "NOT_APPLICABLE"
            ),
            broker_identity_verified_at=(
                identity.verified_at.isoformat() if identity is not None else None
            ),
            broker_identity_environment=(
                identity.environment if identity is not None else None
            ),
            broker_account_id_masked=(
                "*" * max(0, len(account.account_id) - 4) + account.account_id[-4:]
            ),
            broker_account_server=account.server,
            broker_account_currency=account.currency,
            broker_account_trade_mode=account.trade_mode,
            telegram_enabled=settings.telegram_enabled,
            telegram_configured=telegram_configured,
            telegram_status=(
                "READY" if telegram_configured else
                "UNAVAILABLE" if settings.telegram_enabled else
                "DISABLED"
            ),
        )

    def _get_latest_demo_verifications(self) -> dict[str, dict[str, Any]]:
        """Read latest DemoOnlyGuard verification per broker from SQLite evidence store."""
        evidence_path = DEFAULT_BROKER_EVIDENCE_PATH
        if not evidence_path.is_file():
            return {}
        verifications: dict[str, dict[str, Any]] = {}
        try:
            import sqlite3
            with sqlite3.connect(evidence_path, timeout=5.0) as conn:
                cur = conn.cursor()
                rows = cur.execute(
                    """
                    SELECT broker, account_id, checked_field, observed_value, status, verified_at, facts_json
                    FROM broker_account_verifications
                    ORDER BY id DESC
                    """
                ).fetchall()
                for row in rows:
                    broker_key = str(row[0]).strip().lower()
                    if broker_key not in verifications:
                        verifications[broker_key] = {
                            "broker": row[0],
                            "account_id": row[1],
                            "checked_field": row[2],
                            "observed_value": row[3],
                            "status": row[4],
                            "verified_at": row[5],
                            "facts_json": row[6],
                        }
        except Exception:
            pass
        return verifications

    def get_broker_status(self) -> BrokerStatusResponse:
        """Read-only status per active and supported broker from evidence and safety stores."""
        active_broker = settings.effective_broker.strip().lower()
        active_env = settings.environment
        unresolved_count, switch_blocked_reason = self._unresolved_intent_summary()

        # 1. Read safety snapshot without live gateway access
        safety_store = SQLiteExecutionSafetyStore(
            settings.execution_safety_store_path, initialize=False
        )
        snapshot = None
        obs_state = "NOT_OBSERVED"
        emerg_stop = "UNKNOWN"
        exec_auth = "NOT_EVALUATED"
        observed_at = None
        is_fresh = False

        try:
            snapshot = safety_store.read()
        except Exception:
            obs_state = "UNAVAILABLE"

        if snapshot is not None:
            observed_at = snapshot.observed_at.astimezone(datetime.timezone.utc).isoformat()
            emerg_stop = snapshot.emergency_stop_state.value
            exec_auth = snapshot.execution_authorization.value
            age = utc_now() - snapshot.observed_at.astimezone(datetime.timezone.utc)
            if age.total_seconds() > settings.execution_safety_freshness_seconds:
                obs_state = "STALE"
            else:
                obs_state = "OBSERVED"
                is_fresh = True

        # 2. Read latest DemoOnlyGuard verifications from evidence store
        verifications = self._get_latest_demo_verifications()

        def _mask(acc_id: str | None) -> str | None:
            if not acc_id:
                return None
            s = str(acc_id).strip()
            if len(s) <= 4:
                return s
            return "*" * (len(s) - 4) + s[-4:]

        # 3. Known broker catalogue
        known_brokers = [
            ("mt5", "MT5 Demo"),
            ("weltrade", "Weltrade Demo"),
            ("deriv", "Deriv Demo"),
            ("simulation", "Simulation (Test Only)"),
        ]

        broker_items: list[BrokerItemStatusDTO] = []
        active_identity_dto: ActiveBrokerIdentityDTO | None = None

        # Evidence is only attributable to a broker card when the verified account
        # matches that broker's configured demo account. Weltrade historically
        # recorded evidence under the inherited "mt5" key, so an unattributable
        # row must never be shown as an MT5 verification.
        configured_accounts = {
            "mt5": settings.mt5_login,
            "weltrade": settings.effective_weltrade_login,
            "deriv": settings.deriv_options_account_id,
        }

        for b_key, b_name in known_brokers:
            is_active = (b_key == active_broker) or (active_broker.startswith(b_key))
            verif = verifications.get(b_key)
            attribution_note: str | None = None
            if verif is not None and b_key in configured_accounts:
                observed_account = str(verif.get("account_id") or "").strip()
                configured_account = configured_accounts[b_key]
                if configured_account is None:
                    attribution_note = (
                        f"DemoOnlyGuard evidence for account {_mask(observed_account)} is not "
                        f"attributable: no configured {b_name} account identity"
                    )
                    verif = None
                elif observed_account and observed_account != str(configured_account).strip():
                    attribution_note = (
                        f"Latest DemoOnlyGuard evidence belongs to account "
                        f"{_mask(observed_account)}, not the configured {b_name} account "
                        f"{_mask(str(configured_account))}"
                    )
                    verif = None
            demo_guard_status = verif["status"] if verif else "UNVERIFIED"
            demo_guard_verified_at = verif["verified_at"] if verif else None
            is_configured, is_available, error_message = self._broker_configuration_audit(b_key)
            if is_active:
                can_switch = False
                item_blocked_reason: str | None = None
            elif switch_blocked_reason is not None:
                can_switch = False
                item_blocked_reason = switch_blocked_reason
            elif not is_available:
                can_switch = False
                item_blocked_reason = error_message
            else:
                can_switch = True
                item_blocked_reason = None

            # Server & account resolution from settings and evidence
            acc_id: str | None = None
            server: str | None = None
            currency: str | None = None
            trade_mode: str | None = None

            if b_key == "mt5":
                server = getattr(settings, "mt5_server", None)
                acc_id = verif["account_id"] if verif else getattr(settings, "mt5_login", None)
                trade_mode = "demo" if (verif and verif.get("observed_value") == 0) else "demo"
            elif b_key == "weltrade":
                server = settings.effective_weltrade_server
                acc_id = (
                    verif["account_id"]
                    if verif
                    else (
                        None
                        if settings.effective_weltrade_login is None
                        else str(settings.effective_weltrade_login)
                    )
                )
                trade_mode = "demo" if (verif and verif.get("observed_value") == 0) else "demo"
            elif b_key == "deriv":
                server = getattr(settings, "deriv_server", None)
                acc_id = verif["account_id"] if verif else getattr(settings, "deriv_options_account_id", None)
                trade_mode = "demo" if (verif and verif.get("observed_value") == 1) else "demo"
            elif b_key == "simulation":
                server = "in-memory"
                acc_id = "SIMULATED"
                trade_mode = "demo"
                demo_guard_status = "PASSED"

            connected = False
            if is_active:
                connected = is_fresh or (b_key == "simulation")

            masked = _mask(acc_id)
            item_dto = BrokerItemStatusDTO(
                broker=b_key,
                name=b_name,
                is_active=is_active,
                connected=connected,
                is_configured=is_configured,
                is_available=is_available,
                error_message=error_message,
                can_switch=can_switch,
                switch_blocked_reason=item_blocked_reason,
                demo_guard_status=demo_guard_status,
                demo_guard_verified_at=demo_guard_verified_at,
                account_id_masked=masked,
                account_server=server,
                account_currency=currency,
                account_trade_mode=trade_mode,
                environment=active_env if is_active else None,
                notes=attribution_note,
            )
            broker_items.append(item_dto)

            if is_active:
                active_identity_dto = ActiveBrokerIdentityDTO(
                    broker=b_key,
                    account_id_masked=masked,
                    server=server,
                    trade_mode=(trade_mode or "DEMO").upper(),
                    currency=currency,
                    verified_at=demo_guard_verified_at,
                    demo_guard_passed=(demo_guard_status == "PASSED"),
                )

        active_item = next((i for i in broker_items if i.is_active), None)

        return BrokerStatusResponse(
            brokers=broker_items,
            active_broker=active_broker,
            active_broker_identity=active_identity_dto,
            emergency_stop_state=emerg_stop,
            execution_authorization=exec_auth,
            observed_at=observed_at,
            observation_state=obs_state,
            can_switch=switch_blocked_reason is None,
            switch_blocked_reason=switch_blocked_reason,
            unresolved_intent_count=unresolved_count if unresolved_count is not None else -1,
            broker=active_broker,
            environment=active_env,
            connected=active_item.connected if active_item else False,
            last_verified_at=active_item.demo_guard_verified_at if active_item else None,
            identity_state=active_item.demo_guard_status if active_item else "NOT_APPLICABLE",
            account_id_masked=active_item.account_id_masked if active_item else None,
            account_server=active_item.account_server if active_item else None,
            account_currency=active_item.account_currency if active_item else None,
            account_trade_mode=active_item.account_trade_mode if active_item else None,
            broker_execution_enabled=settings.broker_execution_enabled,
        )

    def _unresolved_intent_summary(self) -> tuple[int | None, str | None]:
        """Return (unresolved_count, blocked_reason) from the durable intent store.

        A missing store counts as zero unresolved intents; an unreadable store
        fails closed and blocks broker switching.
        """
        path = Path(settings.intent_store_path)
        if not path.is_file():
            return 0, None
        try:
            store = SQLiteIntentRecordStore(path, initialize=False)
            unresolved = store.list_unresolved()
        except Exception:
            return None, (
                "Durable intent store is unreadable; broker switching is blocked "
                "until execution recovery state can be verified"
            )
        if unresolved:
            return len(unresolved), (
                f"{len(unresolved)} unresolved durable execution intent(s) "
                "(PENDING/UNKNOWN) must be resolved before switching brokers"
            )
        return 0, None

    def _broker_configuration_audit(self, broker: str) -> tuple[bool, bool, str | None]:
        """Return (is_configured, is_available, error_message) for a canonical broker.

        Mirrors the configuration preconditions enforced by broker.factory.get_gateway
        without constructing or connecting any gateway.
        """
        if broker == "simulation":
            return True, True, None
        if broker == "deriv":
            missing = []
            if not settings.deriv_api_token:
                missing.append("JQE_DERIV_API_TOKEN")
            if not settings.deriv_options_account_id:
                missing.append("JQE_DERIV_OPTIONS_ACCOUNT_ID")
            if settings.deriv_expected_environment != "demo":
                return (
                    not missing,
                    False,
                    "JQE_DERIV_EXPECTED_ENVIRONMENT=demo is required for Deriv demo access",
                )
            if missing:
                return False, False, f"Missing required Deriv configuration: {', '.join(missing)}"
            return True, True, None
        if broker == "mt5":
            if (
                settings.mt5_expected_environment is not None
                and settings.mt5_expected_environment != "demo"
            ):
                return True, False, (
                    "Live/real MT5 execution is prohibited; JQE_MT5_EXPECTED_ENVIRONMENT must be 'demo'"
                )
            return True, True, None
        if broker == "weltrade":
            missing = []
            if not settings.weltrade_terminal_path:
                missing.append("JQE_WELTRADE_TERMINAL_PATH")
            if not settings.effective_weltrade_login:
                missing.append("JQE_WELTRADE_DEMO_LOGIN")
            if not settings.effective_weltrade_server:
                missing.append("JQE_WELTRADE_DEMO_SERVER")
            if missing:
                return False, False, (
                    f"Missing required Weltrade configuration: {', '.join(missing)}"
                )
            return True, True, None
        return False, False, f"Unsupported broker: {broker}"

    def select_broker(self, broker: str, reason: str = "") -> SelectBrokerResponse:
        """Validate and persist the operator broker selection.

        Never falls back to simulation: an unavailable real broker is rejected
        with BrokerUnavailableError and nothing is persisted.
        """
        canonical = normalize_broker_name(broker)
        _count, blocked_reason = self._unresolved_intent_summary()
        if blocked_reason is not None:
            raise BrokerSwitchConflictError(blocked_reason)
        _configured, available, error_message = self._broker_configuration_audit(canonical)
        if not available:
            raise BrokerUnavailableError(
                error_message or f"Broker '{canonical}' is not available"
            )
        store = BrokerSelectionStore(settings.broker_selection_store_path)
        store.set_selected_broker(canonical, reason=reason)
        return SelectBrokerResponse(
            selected_broker=canonical,
            persisted=True,
            status=self.get_broker_status(),
        )

    def get_watchlist_cap_usage(
        self, account_scope: str = "default"
    ) -> WatchlistCapUsageResponse:
        """Query DailyInstrumentTradeGuard for each watchlisted instrument.

        Uses the exact same guard and account_scope resolution logic as DigestAssembler
        in monitoring/observation_daemon.py, ensuring dashboard and digest numbers agree.
        """
        store = WatchlistStore(settings.watchlist_store_path)
        items = store.get_items()
        guard = DailyInstrumentTradeGuard(
            settings.daily_instrument_trade_store_path,
            limit=settings.max_daily_trades_per_instrument,
        )
        dtos: list[WatchlistCapUsageDTO] = []
        for item in items:
            usage = guard.usage(account_scope, item.symbol)
            dtos.append(
                WatchlistCapUsageDTO(
                    symbol=item.symbol,
                    timeframe=item.timeframe,
                    scope=item.scope,
                    daily_count=usage.count,
                    daily_limit=usage.limit,
                    daily_remaining=max(0, usage.limit - usage.count),
                    utc_date=usage.utc_date,
                    reset_at=usage.reset_at.isoformat(),
                    available=usage.count < usage.limit,
                )
            )
        return WatchlistCapUsageResponse(
            items=dtos,
            observed_at=utc_now().isoformat(),
        )
