"""Typed, deterministic models for research-only backtesting."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from broker.types import Candle, ExecutionQuantity, Timeframe
from core.exceptions import MarketDataError


class EntryTiming(str, Enum):
    NEXT_CANDLE_OPEN = "NEXT_CANDLE_OPEN"


class SameCandleCollisionPolicy(str, Enum):
    STOP_LOSS_WINS = "STOP_LOSS_WINS"


class BacktestExitReason(str, Enum):
    STOP_LOSS = "STOP_LOSS"
    TAKE_PROFIT = "TAKE_PROFIT"
    TIMEOUT = "TIMEOUT"
    END_OF_DATA = "END_OF_DATA"


@dataclass(frozen=True, slots=True)
class BacktestExecutionAssumptions:
    entry_timing: EntryTiming = EntryTiming.NEXT_CANDLE_OPEN
    spread: float = 0.0
    slippage: float = 0.0
    fee_per_trade: float = 0.0
    same_candle_collision_policy: SameCandleCollisionPolicy = SameCandleCollisionPolicy.STOP_LOSS_WINS
    max_holding_candles: int = 19

    def __post_init__(self) -> None:
        if any(value < 0 for value in (self.spread, self.slippage, self.fee_per_trade)):
            raise ValueError("Backtest costs cannot be negative")
        if self.max_holding_candles <= 0:
            raise ValueError("max_holding_candles must be positive")


@dataclass(frozen=True, slots=True)
class BacktestRiskConfiguration:
    risk_percent: float = 1.0
    minimum_confidence: int = 70

    def __post_init__(self) -> None:
        if not 0 < self.risk_percent <= 100:
            raise ValueError("risk_percent must be in (0, 100]")
        if not 0 <= self.minimum_confidence <= 100:
            raise ValueError("minimum_confidence must be in [0, 100]")


@dataclass(frozen=True, slots=True)
class CandleDatasetSnapshot:
    provider: str
    symbol: str
    timeframe: Timeframe
    candles: tuple[Candle, ...]

    def __post_init__(self) -> None:
        if not self.provider.strip() or not self.symbol.strip() or not self.candles:
            raise MarketDataError("Backtest dataset identity and candles are required")
        times = tuple(candle.time for candle in self.candles)
        if any(value.tzinfo is None for value in times):
            raise MarketDataError("Backtest candle timestamps must be timezone-aware")
        if any(current <= previous for previous, current in zip(times, times[1:])):
            raise MarketDataError("Backtest candles must be unique and strictly increasing")
        if len({candle.source.strip().lower() for candle in self.candles}) > 1:
            raise MarketDataError("Backtest dataset cannot mix candle sources")
        for candle in self.candles:
            values = (candle.open, candle.high, candle.low, candle.close)
            if not all(math.isfinite(float(value)) and float(value) > 0 for value in values):
                raise MarketDataError("Backtest OHLC values must be positive and finite")
            if candle.high < max(candle.open, candle.close) or candle.low > min(candle.open, candle.close) or candle.high < candle.low:
                raise MarketDataError("Backtest candle OHLC invariants failed")

    @property
    def start(self) -> datetime:
        return self.candles[0].time.astimezone(timezone.utc)

    @property
    def end(self) -> datetime:
        return self.candles[-1].time.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class BacktestTrade:
    trade_id: int
    symbol: str
    timeframe: Timeframe
    direction: str
    signal_timestamp: datetime
    entry_timestamp: datetime
    entry_price: float
    exit_timestamp: datetime
    exit_price: float
    stop_price: float
    target_price: float
    quantity: ExecutionQuantity
    gross_pnl: float
    costs: float
    net_pnl: float
    balance_before: float
    balance_after: float
    holding_candles: int
    exit_reason: BacktestExitReason

    def __getitem__(self, key: str) -> Any:
        """Temporary compatibility for existing analytics/research callers."""
        aliases = {
            "type": "direction", "profit": "net_pnl", "entry": "entry_price",
            "exit": "exit_price", "duration_candles": "holding_candles",
            "lot_size": "quantity",
        }
        value = getattr(self, aliases.get(key, key))
        return value.value if key == "lot_size" else value

    def __contains__(self, key: object) -> bool:
        """Support legacy mapping-style analytics without sequence iteration."""
        if not isinstance(key, str):
            return False
        aliases = {
            "type": "direction", "profit": "net_pnl", "entry": "entry_price",
            "exit": "exit_price", "duration_candles": "holding_candles",
            "lot_size": "quantity",
        }
        return hasattr(self, aliases.get(key, key))


@dataclass(frozen=True, slots=True)
class BacktestResult:
    provider: str
    symbol: str
    timeframe: Timeframe
    dataset_start: datetime
    dataset_end: datetime
    candle_count: int
    initial_capital: float
    strategy: dict[str, Any]
    risk: BacktestRiskConfiguration
    execution: BacktestExecutionAssumptions
    ending_capital: float
    absolute_pnl: float
    return_percent: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    break_even_trades: int
    win_rate_percent: float
    gross_profit: float
    gross_loss: float
    profit_factor: float | None
    profit_factor_status: str
    average_trade_pnl: float
    average_winner: float | None
    average_loser: float | None
    largest_winner: float | None
    largest_loser: float | None
    expectancy: float
    maximum_drawdown: float
    maximum_drawdown_percent: float
    drawdown_basis: str
    average_holding_candles: float
    maximum_consecutive_wins: int
    maximum_consecutive_losses: int
    trades: tuple[BacktestTrade, ...]

    def to_json_bytes(self) -> bytes:
        def normalize(value: Any) -> Any:
            if hasattr(value, "model_dump"):
                return normalize(value.model_dump())
            if isinstance(value, datetime):
                return value.astimezone(timezone.utc).isoformat(timespec="microseconds")
            if isinstance(value, Enum):
                return value.value
            if isinstance(value, dict):
                return {str(k): normalize(v) for k, v in sorted(value.items())}
            if isinstance(value, (list, tuple)):
                return [normalize(item) for item in value]
            return value

        return (json.dumps(normalize(asdict(self)), sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")

    def to_dict(self) -> dict[str, Any]:
        """Return the normalized canonical payload used for serialization."""
        return json.loads(self.to_json_bytes().decode("utf-8"))
