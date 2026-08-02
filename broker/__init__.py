"""The broker layer: a broker-agnostic gateway interface plus one
implementation per supported broker.

The Quant Core should only ever import from here:

    >>> from broker import BrokerGateway, get_gateway
    >>> gateway = get_gateway()  # implementation chosen by config.settings.broker

Never import a concrete gateway class (``DerivGateway``, ``MT5Gateway``,
``SimulationGateway``) or a broker SDK (``MetaTrader5``, ``websockets``)
outside of this package — see docs/architecture.md, "Broker layer".
"""

from broker.base import BrokerGateway
from broker.deriv_gateway import DerivGateway
from broker.factory import get_gateway
from broker.mt5_gateway import MT5Gateway
from broker.simulation_gateway import SimulationGateway
from broker.types import (
    AccountInfo,
    Candle,
    OrderRequest,
    OrderResult,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
    Tick,
    Timeframe,
    TradeHistoryEntry,
)

__all__ = [
    "AccountInfo",
    "BrokerGateway",
    "Candle",
    "DerivGateway",
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
    "get_gateway",
]
