"""Broker-agnostic domain types shared by every :class:`~broker.base.BrokerGateway`
implementation.

These are the only shapes the Quant Core is ever meant to see — no
implementation (:mod:`broker.deriv_gateway`, :mod:`broker.mt5_gateway`,
:mod:`broker.simulation_gateway`) exposes broker-native objects (an MT5
``TradeRequest`` struct, a Deriv ``contract`` dict, ...) past its own
boundary. Every gateway method takes and returns these Pydantic models,
so downstream code depends on one stable contract regardless of which
broker is configured.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import math
from typing import Any

from pydantic import BaseModel, Field, model_validator


class Timeframe(str, Enum):
    """A broker-agnostic candle timeframe.

    Each :class:`~broker.base.BrokerGateway` implementation maps these
    to its own native representation (MT5's ``TIMEFRAME_*`` constants,
    Deriv's granularity-in-seconds, ...).
    """

    M1 = "M1"
    M5 = "M5"
    M15 = "M15"
    M30 = "M30"
    H1 = "H1"
    H4 = "H4"
    D1 = "D1"


#: Seconds per candle for each timeframe — used by gateways whose native
#: API expresses granularity in seconds (e.g. Deriv's ``ticks_history``).
TIMEFRAME_SECONDS: dict[Timeframe, int] = {
    Timeframe.M1: 60,
    Timeframe.M5: 300,
    Timeframe.M15: 900,
    Timeframe.M30: 1800,
    Timeframe.H1: 3600,
    Timeframe.H4: 14400,
    Timeframe.D1: 86400,
}


class OrderSide(str, Enum):
    """Direction of an order or position."""

    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    """Broker-neutral execution types supported by the order contract."""

    MARKET = "MARKET"
    BUY_STOP = "BUY_STOP"
    SELL_STOP = "SELL_STOP"
    STOP_LIMIT = "STOP_LIMIT"


class ExecutionQuantityUnit(str, Enum):
    """Explicit financial unit carried by a broker-bound order quantity."""

    SIMULATION_UNITS = "SIMULATION_UNITS"
    DERIV_STAKE = "DERIV_STAKE"
    MT5_LOTS = "MT5_LOTS"


class ExecutionQuantity(BaseModel):
    """A positive finite broker-bound quantity with non-ambiguous units."""

    model_config = {"frozen": True}

    value: float = Field(gt=0, allow_inf_nan=False)
    unit: ExecutionQuantityUnit


class OrderStatus(str, Enum):
    """Outcome of a submitted order."""

    SUBMITTED = "SUBMITTED"
    FILLED = "FILLED"
    REJECTED = "REJECTED"


class AccountInfo(BaseModel):
    """Broker account snapshot.

    Attributes:
        account_id: Broker-assigned account/login identifier.
        balance: Cash balance, in ``currency``.
        currency: ISO-ish currency code (e.g. ``"USD"``).
        equity: Balance plus floating P/L of open positions, if the
            broker reports it separately from balance.
        leverage: Account leverage ratio, if applicable to this broker.
    """

    account_id: str
    balance: float
    currency: str
    equity: float | None = None
    leverage: float | None = None
    server: str | None = None
    trade_mode: str | None = None


class AccountIdentity(BaseModel):
    """Stable, non-secret broker account identity used for durable scoping."""

    model_config = {"frozen": True, "extra": "forbid"}

    broker: str
    account_id: str
    server: str | None = None
    currency: str
    trade_mode: str

    @property
    def scope(self) -> str:
        return f"{self.broker.strip().lower()}:{self.account_id.strip()}"


class Candle(BaseModel):
    """One broker-neutral OHLC(V) candle with explicit provenance."""

    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None
    source: str = "unknown"


class ClosedMarketObservation(BaseModel):
    """An immutable, broker-neutral closed candle used by one execution cycle.

    This is factual market context only.  It deliberately contains no account,
    authority, strategy, or risk fields.  ``closed_at`` is the proven boundary
    after which the provider candle may be evaluated.
    """

    model_config = {"frozen": True, "extra": "forbid"}

    canonical_symbol: str
    source: str
    provider_symbol: str
    timeframe: Timeframe
    candle_opened_at: datetime
    closed_at: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None

    def model_post_init(self, __context: Any) -> None:
        for name in ("canonical_symbol", "source", "provider_symbol"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must be nonblank")
        if self.candle_opened_at.tzinfo is None or self.closed_at.tzinfo is None:
            raise ValueError("market observation timestamps must be timezone-aware")
        if self.closed_at <= self.candle_opened_at:
            raise ValueError("closed_at must be after candle_opened_at")
        values = (self.open, self.high, self.low, self.close)
        if not all(math.isfinite(value) and value > 0 for value in values):
            raise ValueError("market observation OHLC values must be positive and finite")
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close):
            raise ValueError("market observation OHLC invariants failed")
        if self.low > self.high:
            raise ValueError("market observation low cannot exceed high")
        if self.volume is not None and (not math.isfinite(self.volume) or self.volume < 0):
            raise ValueError("market observation volume must be finite and nonnegative")

    @property
    def reference_price(self) -> float:
        """Checkpoint-1 deterministic simulation reference: the candle close."""
        return self.close

    def is_closed_at(self, observed_at: datetime) -> bool:
        """Return true only once the provider's candle interval has elapsed."""
        if observed_at.tzinfo is None:
            return False
        return observed_at.astimezone(timezone.utc) >= self.closed_at.astimezone(timezone.utc)


class Tick(BaseModel):
    """One live price update for a symbol."""

    time: datetime
    symbol: str
    bid: float
    ask: float
    last: float | None = None


class OrderRequest(BaseModel):
    """A mechanical instruction to submit an order to the broker.

    This is intentionally minimal: no risk sizing, no strategy
    rationale, no trade-management policy. Those are the concern of
    later milestones (Risk Engine, Execution Engine) — a
    :class:`~broker.base.BrokerGateway` only ever executes the request
    it's handed.

    Attributes:
        symbol: Instrument symbol, in the broker-agnostic form the
            caller uses (each gateway resolves it to the broker's
            native symbol internally).
        side: Direction of the order.
        quantity: Explicit value and financial unit. Gateways reject units
            that do not match their broker contract.
        order_type: Market or pending execution type.
        entry_price: Trigger price required for pending orders.
        stop_limit_price: Limit price required for stop-limit orders.
        stop_loss: Mandatory positive broker-native protective threshold. MT5
            gateways interpret it as an absolute price; Deriv multiplier
            contracts interpret it as an account-currency loss amount.
        take_profit: Optional positive broker-native profit threshold.
        idempotency_key: Execution intent identity propagated to brokers that
            support request metadata. Gateways that do not support such
            metadata still receive the same explicit request type.
    """

    model_config = {"extra": "forbid"}

    symbol: str
    side: OrderSide
    quantity: ExecutionQuantity
    order_type: OrderType = OrderType.MARKET
    entry_price: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    stop_limit_price: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    stop_loss: float = Field(gt=0, allow_inf_nan=False)
    take_profit: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    idempotency_key: str | None = None
    magic_number: int | None = None
    order_comment: str | None = None

    @model_validator(mode="after")
    def validate_order_type_fields(self) -> "OrderRequest":
        pending = self.order_type is not OrderType.MARKET
        if pending and self.entry_price is None:
            raise ValueError("entry_price is required for pending orders")
        if not pending and (self.entry_price is not None or self.stop_limit_price is not None):
            raise ValueError("market orders cannot specify pending-order prices")
        if self.order_type is OrderType.STOP_LIMIT:
            if self.stop_limit_price is None:
                raise ValueError("stop_limit_price is required for stop-limit orders")
        elif self.stop_limit_price is not None:
            raise ValueError("stop_limit_price is only valid for stop-limit orders")
        if self.order_type is OrderType.BUY_STOP and self.side is not OrderSide.BUY:
            raise ValueError("BUY_STOP requires BUY side")
        if self.order_type is OrderType.SELL_STOP and self.side is not OrderSide.SELL:
            raise ValueError("SELL_STOP requires SELL side")
        return self

    @property
    def volume(self) -> float:
        """Deprecated read-only numeric accessor; never identifies financial units."""
        return self.quantity.value


class OrderResult(BaseModel):
    """Outcome of a submitted order.

    Attributes:
        order_id: Broker-assigned identifier for the resulting order or
            contract. Empty string if the order was rejected before one
            was assigned.
        status: Whether the order filled, was rejected, or is pending.
        symbol: Echoes the request's symbol.
        side: Echoes the request's side.
        volume: Echoes the request's volume.
        filled_price: Execution price, if filled.
        raw: The broker's raw response payload, for debugging —
            never relied upon by calling code for control flow.
    """

    order_id: str
    status: OrderStatus
    symbol: str
    side: OrderSide
    volume: float
    filled_price: float | None = None
    transaction_id: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class Position(BaseModel):
    """An open position/contract."""

    position_id: str
    symbol: str
    side: OrderSide
    volume: float
    open_price: float
    current_price: float | None = None
    profit: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    opened_at: datetime | None = None
    transaction_id: str | None = None
    contract_type: str | None = None
    magic: int | None = None
    comment: str | None = None


class TradeHistoryEntry(BaseModel):
    """A single closed, historical trade."""

    trade_id: str
    symbol: str
    side: OrderSide
    volume: float
    open_price: float
    close_price: float
    profit: float
    opened_at: datetime
    closed_at: datetime
    transaction_id: str | None = None
    contract_type: str | None = None


class TradeHistoryCompleteness(str, Enum):
    """Whether a history snapshot proves coverage of its requested interval."""

    COMPLETE = "COMPLETE"
    TRUNCATED = "TRUNCATED"
    UNKNOWN = "UNKNOWN"


class TradeHistorySnapshot(BaseModel):
    """Closed trades plus explicit evidence about interval completeness."""

    trades: list[TradeHistoryEntry] = Field(default_factory=list)
    completeness: TradeHistoryCompleteness = TradeHistoryCompleteness.UNKNOWN
    coverage_start: datetime | None = None
    coverage_end: datetime | None = None

    def covers(self, start: datetime, end: datetime) -> bool:
        """Return true only for positively established interval coverage."""
        return (
            self.completeness is TradeHistoryCompleteness.COMPLETE
            and self.coverage_start is not None
            and self.coverage_end is not None
            and self.coverage_start <= start
            and self.coverage_end >= end
        )
