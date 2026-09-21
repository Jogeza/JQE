"""The broker layer: a broker-agnostic gateway interface plus one
implementation per supported broker.

The Quant Core should only ever import from here:

    >>> from broker import BrokerGateway, get_gateway
    >>> gateway = get_gateway()  # chosen by config.settings.effective_broker
    ...                          # (persisted operator selection wins, else JQE_BROKER)

Never import a concrete gateway class (``DerivGateway``, ``MT5Gateway``,
``SimulationGateway``) or a broker SDK (``MetaTrader5``, ``websockets``)
outside of this package — see docs/architecture.md, "Broker layer".
"""

from broker.base import BrokerGateway
from broker.demo_guard import DemoAccountVerification, DemoOnlyGuard
from broker.deriv_demo import DerivDemoGateway
from broker.deriv_gateway import DerivGateway
from broker.factory import get_gateway
from broker.mt5_demo import MT5DemoGateway
from broker.mt5_gateway import MT5Gateway
from broker.simulation_gateway import SimulationGateway
from broker.types import (
    AccountInfo,
    Candle,
    ClosedMarketObservation,
    OrderRequest,
    OrderResult,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
    Tick,
    Timeframe,
    TradeHistoryEntry,
    TradeHistoryCompleteness,
    TradeHistorySnapshot,
)
from core.exceptions import UnsafeBrokerAccountError

__all__ = [
    "AccountInfo",
    "BrokerGateway",
    "Candle",
    "ClosedMarketObservation",
    "DemoAccountVerification",
    "DemoOnlyGuard",
    "DerivDemoGateway",
    "DerivGateway",
    "MT5DemoGateway",
    "MT5Gateway",
    "OrderRequest",
    "OrderResult",
    "OrderSide",
    "OrderStatus",
    "OrderType",
    "Position",
    "SimulationGateway",
    "Tick",
    "Timeframe",
    "TradeHistoryEntry",
    "TradeHistoryCompleteness",
    "TradeHistorySnapshot",
    "UnsafeBrokerAccountError",
    "get_gateway",
]
