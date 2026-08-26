"""JQE API Data Transfer Objects (DTOs).

Defines typed Pydantic models for API responses, establishing a strict
boundary between Quant Core domain models and HTTP API representations.
"""

from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field


class MarketSummaryResponse(BaseModel):
    """Current market summary and latest indicator snapshot."""

    symbol: str
    timeframe: str
    latest_close: float
    latest_high: float
    latest_low: float
    latest_open: float
    spread: float
    atr: float
    rsi: float
    ema50: float | None = None
    ema200: float | None = None
    timestamp: str | None = None
    price_decimals: int = Field(default=5, ge=0, le=10)


class CandleItemDTO(BaseModel):
    """Single candle item with computed indicator values."""

    time: str
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    EMA50: float | None = None
    EMA200: float | None = None
    RSI: float | None = None
    ATR: float | None = None


class CandlesResponse(BaseModel):
    """Historical candle series with indicator data."""

    symbol: str
    timeframe: str
    count: int
    candles: list[CandleItemDTO] = Field(default_factory=list)
    price_decimals: int = Field(default=5, ge=0, le=10)


class ConfidenceBreakdownDTO(BaseModel):
    """Institutional 6-factor confidence model breakdown."""

    trend_score: int = Field(ge=0, le=25)
    structure_score: int = Field(ge=0, le=20)
    liquidity_score: int = Field(ge=0, le=20)
    momentum_score: int = Field(ge=0, le=15)
    volatility_score: int = Field(ge=0, le=10)
    risk_score: int = Field(ge=0, le=10)
    total: int = Field(ge=0, le=100)
    factors: dict[str, str] = Field(default_factory=dict)


class TradePlanDTO(BaseModel):
    """Structured trade setup with risk parameters and direction invariants."""

    symbol: str
    signal: Literal["BUY", "SELL", "NO_TRADE"]
    confidence: int = Field(ge=0, le=100)
    quality: str = "POOR"
    score: int = 0
    setup_type: str = "NO_SETUP"
    entry: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    risk_reward: float | None = None
    position_size: float | None = None
    risk_percent: float | None = None
    risk_amount: float | None = None
    invalidation: str | None = None
    warnings: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    is_valid: bool = False


class SignalResponse(BaseModel):
    """Complete strategy decision, confidence model, and trade plan."""

    symbol: str
    signal: Literal["BUY", "SELL", "NO_TRADE"]
    confidence: int = Field(ge=0, le=100)
    quality: str = "POOR"
    score: int = 0
    reasons: list[str] = Field(default_factory=list)
    regime: str = "UNKNOWN"
    trend: str = "UNKNOWN"
    momentum: str = "UNKNOWN"
    volatility: str = "UNKNOWN"
    liquidity: str = "UNKNOWN"
    confidence_breakdown: ConfidenceBreakdownDTO | None = None
    trade_plan: TradePlanDTO | None = None
    generated_at: str | None = None
    price_decimals: int = Field(default=5, ge=0, le=10)


class RiskStatusResponse(BaseModel):
    """Account risk metrics, daily limits status, and trade approval evaluation."""

    balance: float
    equity: float
    currency: str = "USD"
    max_daily_loss: float
    max_trades_daily: int
    daily_trades_count: int = 0
    daily_loss_percent: float = 0.0
    risk_allowed: bool = True
    risk_message: str = "Limits OK"
    approved: bool = False
    rejection_reason: str = ""
    recommended_lot_size: float = 0.0
    risk_percent: float = 0.0


class PositionDTO(BaseModel):
    """Open position representation."""

    id: str
    symbol: str
    side: str
    volume: float
    open_price: float
    current_price: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    profit: float = 0.0
    price_decimals: int = Field(default=5, ge=0, le=10)


class TradeHistoryDTO(BaseModel):
    """Historical executed trade record."""

    id: str
    symbol: str
    side: str
    volume: float
    open_price: float
    close_price: float
    profit: float
    open_time: str
    close_time: str
    price_decimals: int = Field(default=5, ge=0, le=10)


class ExecutionStateResponse(BaseModel):
    """Execution layer state, open positions, and recent trades."""

    broker: str
    connected: bool
    open_positions_count: int = 0
    positions: list[PositionDTO] = Field(default_factory=list)
    recent_trades_count: int = 0
    recent_trades: list[TradeHistoryDTO] = Field(default_factory=list)
    currency: str


class PerformanceSummaryResponse(BaseModel):
    """Quantitative performance analytics derived from trade history."""

    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate_percent: float = 0.0
    profit_factor: float = 0.0
    max_drawdown_amount: float = Field(default=0.0, description="Maximum realized P&L drawdown in account currency")
    max_drawdown_percent: float | None = Field(default=None, description="Maximum drawdown percentage; null when historical equity is unavailable")
    drawdown_amount_unit: str = "account_currency"
    drawdown_percent_unit: str = "percent"
    currency: str | None = None
    average_trade: float = 0.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    net_profit: float = 0.0


class SystemStatusResponse(BaseModel):
    """System health, configuration, and broker connectivity."""

    environment: str
    broker: str
    broker_connected: bool
    default_symbol: str
    default_timeframe: str
    min_confidence_threshold: int
    server_time: str
    status: str = "ONLINE"
