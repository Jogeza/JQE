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

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


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
    """Order execution type.

    Only ``MARKET`` is supported at this stage — this milestone builds
    the gateway's mechanical order-submission capability only, not an
    execution engine with pending/limit order strategies. Extend this
    enum when that becomes real scope.
    """

    MARKET = "MARKET"


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


class Candle(BaseModel):
    """One OHLC(V) candle."""

    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


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
        volume: Position size. Units are broker-specific (MT5 lots,
            Deriv stake amount, ...) — callers targeting multiple
            brokers must account for this until a unified sizing
            concept exists (tracked for the Risk Engine milestone).
        order_type: Execution type. Only ``MARKET`` is currently
            supported.
        stop_loss: Absolute stop-loss price, if any.
        take_profit: Absolute take-profit price, if any.
    """

    symbol: str
    side: OrderSide
    volume: float = Field(gt=0)
    order_type: OrderType = OrderType.MARKET
    stop_loss: float | None = None
    take_profit: float | None = None


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
