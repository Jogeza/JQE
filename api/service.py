"""JQE Application Service Boundary.

Coordinates read-only queries against Quant Core domain services
(BrokerGateway, StrategyEngine, RiskEngine, Performance Analytics).
Encapsulates all domain coordination so the API router remains a thin HTTP layer.
"""

from __future__ import annotations

import datetime
from typing import Any

import pandas as pd

from api.dto import (
    CandleItemDTO,
    CandlesResponse,
    ConfidenceBreakdownDTO,
    ExecutionStateResponse,
    ExecutionSafetyResponse,
    MarketSummaryResponse,
    PerformanceSummaryResponse,
    PositionDTO,
    RiskStatusResponse,
    SignalResponse,
    SystemStatusResponse,
    TradeHistoryDTO,
    TradePlanDTO,
)
from broker.base import BrokerGateway
from broker.factory import get_gateway
from broker.types import Timeframe
from config.settings import settings
from core.data_validator import validate_market_data
from core.exceptions import MarketDataError
from core.indicators import calculate_indicators
from core.regime import detect_regime
from execution.safety import SQLiteExecutionSafetyStore, utc_now
from risk.risk_engine import RiskEngine
from strategy.strategy_engine import StrategyEngine
from strategy.pipeline import generate_trading_signal

_TIMEFRAME_MAP: dict[str, Timeframe] = {tf.value: tf for tf in Timeframe}


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
        strategy_engine: StrategyEngine | None = None,
        risk_engine: RiskEngine | None = None,
    ) -> None:
        self._gateway = gateway
        self.strategy_engine = strategy_engine or StrategyEngine()
        self.risk_engine = risk_engine or RiskEngine()

    def _get_gateway(self) -> BrokerGateway:
        if self._gateway is not None:
            return self._gateway
        return get_gateway(settings)

    async def get_market_summary(
        self,
        symbol: str | None = None,
        timeframe_str: str | None = None,
        count: int | None = None,
    ) -> MarketSummaryResponse:
        """Retrieves latest market data and computes key indicators."""
        target_symbol = symbol if isinstance(symbol, str) and symbol else settings.default_symbol
        tf_name = timeframe_str if isinstance(timeframe_str, str) and timeframe_str else settings.default_timeframe
        tf = _TIMEFRAME_MAP.get(tf_name, Timeframe.H1)
        candle_count = count if isinstance(count, int) and count > 0 else settings.default_candle_count

        gateway = self._get_gateway()
        async with gateway:
            candles = await gateway.get_candles(
                symbol=target_symbol, timeframe=tf, count=candle_count
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
            spread=float(latest.get("spread", 1.0)),
            atr=float(latest.get("ATR", 0.0)),
            rsi=float(latest.get("RSI", 50.0)),
            ema50=float(latest["EMA50"]) if "EMA50" in latest and pd.notna(latest["EMA50"]) else None,
            ema200=float(latest["EMA200"]) if "EMA200" in latest and pd.notna(latest["EMA200"]) else None,
            timestamp=timestamp,
            price_decimals=_price_decimals(target_symbol),
        )

    async def get_market_candles(
        self,
        symbol: str | None = None,
        timeframe_str: str | None = None,
        count: int = 50,
    ) -> CandlesResponse:
        """Retrieves recent candles with computed indicators for charting."""
        target_symbol = symbol if isinstance(symbol, str) and symbol else settings.default_symbol
        tf_name = timeframe_str if isinstance(timeframe_str, str) and timeframe_str else settings.default_timeframe
        tf = _TIMEFRAME_MAP.get(tf_name, Timeframe.H1)
        candle_count = count if isinstance(count, int) and count > 0 else 50

        gateway = self._get_gateway()
        async with gateway:
            candles = await gateway.get_candles(symbol=target_symbol, timeframe=tf, count=candle_count)

        if not candles:
            return CandlesResponse(
                symbol=target_symbol,
                timeframe=tf.value,
                count=0,
                candles=[],
                price_decimals=_price_decimals(target_symbol),
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
                    volume=float(row.get("volume", 0.0)),
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
        )

    async def get_strategy_signal(
        self,
        symbol: str | None = None,
        timeframe_str: str | None = None,
        count: int | None = None,
    ) -> SignalResponse:
        """Evaluates current market data through the canonical StrategyEngine."""
        target_symbol = symbol if isinstance(symbol, str) and symbol else settings.default_symbol
        tf_name = timeframe_str if isinstance(timeframe_str, str) and timeframe_str else settings.default_timeframe
        tf = _TIMEFRAME_MAP.get(tf_name, Timeframe.H1)
        candle_count = count if isinstance(count, int) and count > 0 else settings.default_candle_count

        gateway = self._get_gateway()
        async with gateway:
            candles = await gateway.get_candles(
                symbol=target_symbol, timeframe=tf, count=candle_count
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
                position_size=None,
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

    async def get_risk_status(
        self,
        symbol: str | None = None,
        timeframe_str: str | None = None,
    ) -> RiskStatusResponse:
        """Evaluates account limits and trade sizing through the RiskEngine."""
        target_symbol = symbol if isinstance(symbol, str) and symbol else settings.default_symbol
        tf_name = timeframe_str if isinstance(timeframe_str, str) and timeframe_str else settings.default_timeframe
        tf = _TIMEFRAME_MAP.get(tf_name, Timeframe.H1)

        gateway = self._get_gateway()
        async with gateway:
            account = await gateway.get_account_info()
            candles = await gateway.get_candles(
                symbol=target_symbol, timeframe=tf, count=settings.default_candle_count
            )

        limits_ok, limit_msg = self.risk_engine.evaluate_limits()

        approved = False
        rejection_reason = "No market data"
        risk_pct = 0.0
        authorized_risk_amount: float | None = None
        execution_quantity_value: float | None = None
        execution_quantity_unit: str | None = None
        execution_quantity_reason = "Risk authorization unavailable: no market data"

        if candles:
            df = pd.DataFrame([c.model_dump() for c in candles])
            if validate_market_data(df):
                df = calculate_indicators(df)
                regime = detect_regime(df)
                decision = generate_trading_signal(
                    df, symbol=target_symbol, regime=regime, engine=self.strategy_engine,
                    include_details=True,
                )
                risk_decision = self.risk_engine.approve_trade(
                    {"signal": decision["signal"], "confidence": decision["confidence"]},
                    df,
                    balance=account.balance,
                    enforce_limits=True,
                )
                approved = risk_decision.get("approved", False)
                rejection_reason = risk_decision.get("reason", "")
                risk_pct = risk_decision.get("risk_percent", 0.0)
                if approved:
                    authorized_risk_amount = float(
                        risk_decision["authorized_risk_amount"]
                    )
                    plan = decision.get("trade_plan")
                    if settings.broker == "mt5":
                        execution_quantity_reason = "MT5 execution is disabled"
                    elif (
                        plan is None
                        or not plan.is_valid()
                        or plan.entry is None
                        or plan.stop_loss is None
                    ):
                        execution_quantity_reason = (
                            "Executable quantity unavailable: trade plan is incomplete"
                        )
                    else:
                        sizing = self.risk_engine.authorize_execution_quantity(
                            broker=settings.broker,
                            balance=account.balance,
                            risk_percent=risk_pct,
                            entry=plan.entry,
                            stop_loss=plan.stop_loss,
                        )
                        execution_quantity_reason = sizing.reason
                        if sizing.risk_verifiable and sizing.quantity is not None:
                            execution_quantity_value = sizing.quantity.value
                            execution_quantity_unit = sizing.quantity.unit.value
                else:
                    execution_quantity_reason = rejection_reason or "Risk blocked"

        return RiskStatusResponse(
            balance=account.balance,
            equity=account.equity,
            currency=account.currency,
            max_daily_loss=self.risk_engine.max_daily_loss,
            max_trades_daily=self.risk_engine.max_trades_daily,
            daily_trades_count=self.risk_engine._daily_trades_count,
            daily_loss_percent=self.risk_engine._daily_realized_loss_percent,
            risk_allowed=limits_ok,
            risk_message=limit_msg,
            approved=approved,
            rejection_reason=rejection_reason,
            risk_authorized=approved,
            authorized_risk_amount=authorized_risk_amount,
            authorized_risk_percent=risk_pct if approved else None,
            execution_quantity_available=(
                execution_quantity_value is not None
                and execution_quantity_unit is not None
            ),
            execution_quantity_value=execution_quantity_value,
            execution_quantity_unit=execution_quantity_unit,
            execution_quantity_reason=execution_quantity_reason,
            recommended_lot_size=0.0,
            risk_percent=risk_pct,
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

    async def get_execution_state(self) -> ExecutionStateResponse:
        """Retrieves open positions and recent executed trades from the broker."""
        gateway = self._get_gateway()
        async with gateway:
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
                id=t.id,
                symbol=t.symbol,
                side=t.side.value,
                volume=t.volume,
                open_price=t.open_price,
                close_price=t.close_price,
                profit=t.profit,
                open_time=t.open_time.isoformat() if hasattr(t.open_time, "isoformat") else str(t.open_time),
                close_time=t.close_time.isoformat() if hasattr(t.close_time, "isoformat") else str(t.close_time),
                price_decimals=_price_decimals(t.symbol),
            )
            for t in history
        ]

        return ExecutionStateResponse(
            broker=settings.broker,
            connected=is_conn,
            open_positions_count=len(pos_dtos),
            positions=pos_dtos,
            recent_trades_count=len(trade_dtos),
            recent_trades=trade_dtos,
            currency=account.currency,
        )

    async def get_performance_summary(self) -> PerformanceSummaryResponse:
        """Computes statistical performance metrics over closed trade history."""
        gateway = self._get_gateway()
        async with gateway:
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

    async def get_system_status(self) -> SystemStatusResponse:
        """Retrieves system status, broker name, and active settings."""
        gateway = self._get_gateway()
        async with gateway:
            is_conn = gateway.is_connected

        return SystemStatusResponse(
            environment=settings.environment,
            broker=settings.broker,
            broker_connected=is_conn,
            default_symbol=settings.default_symbol,
            default_timeframe=settings.default_timeframe,
            min_confidence_threshold=settings.min_confidence_threshold,
            server_time=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            status="ONLINE",
        )
