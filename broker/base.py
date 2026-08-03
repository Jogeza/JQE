"""The broker-agnostic gateway interface the Quant Core depends on.

Every concrete broker integration (:class:`~broker.deriv_gateway.DerivGateway`,
:class:`~broker.mt5_gateway.MT5Gateway`,
:class:`~broker.simulation_gateway.SimulationGateway`, and any future
one — Binance, Interactive Brokers, ...) implements
:class:`BrokerGateway`. Code outside the ``broker`` package should
depend on this interface only, never on a concrete implementation or
on a broker's native SDK/protocol — that's what keeps the Quant Core
(market intelligence, strategy, risk, execution, analytics) free of
broker-specific imports.

Scope for this milestone ("Broker Foundation"): reliable read/connect
services only — authentication, account info, market data (candles and
ticks), a mechanical order-submission call, and position/history
retrieval. Execution policy, strategy logic, and risk decisions are
explicitly out of scope here; they consume this interface in later
milestones.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from datetime import datetime
from types import TracebackType
from typing import Self

from broker.types import (
    AccountInfo,
    Candle,
    OrderRequest,
    OrderResult,
    Position,
    Tick,
    Timeframe,
    TradeHistoryEntry,
)


class BrokerGateway(ABC):
    """Abstract broker gateway. See module docstring for scope and intent."""

    @abstractmethod
    async def connect(self) -> None:
        """Establishes and authenticates the connection to the broker.

        Raises:
            core.exceptions.BrokerConnectionError: If the connection
                cannot be established.
            core.exceptions.BrokerAuthenticationError: If the
                connection succeeds but authentication fails.
        """

    @abstractmethod
    async def disconnect(self) -> None:
        """Closes the connection to the broker. Safe to call when not connected."""

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Whether :meth:`connect` has succeeded and :meth:`disconnect` has not been called since."""

    @abstractmethod
    async def get_account_info(self) -> AccountInfo:
        """Retrieves the current account balance and related account state.

        Raises:
            core.exceptions.BrokerConnectionError: If not connected, or
                the broker call fails.
        """

    @abstractmethod
    async def get_candles(
        self, symbol: str, timeframe: Timeframe, count: int, end: datetime | None = None
    ) -> list[Candle]:
        """Retrieves historical candles for a symbol.

        Args:
            symbol: Instrument symbol, in the broker-agnostic form this
                gateway expects (each implementation documents its own
                symbol conventions).
            timeframe: Candle timeframe.
            count: Number of candles to retrieve.
            end: If given, retrieves the ``count`` candles ending at or
                before this timestamp — a historical range query, used
                by ``data.historical.HistoricalDataService`` for gap
                filling. If ``None`` (default), retrieves the most
                recent ``count`` candles ending now — unchanged from
                this method's original behavior.

        Returns:
            Candles ordered oldest to newest. May be shorter than
            ``count`` if the broker has less history available.

        Raises:
            core.exceptions.MarketDataError: If candle data cannot be
                retrieved.
        """

    @abstractmethod
    def stream_ticks(self, symbol: str) -> AsyncIterator[Tick]:
        """Streams live ticks for a symbol until the caller stops iterating.

        Args:
            symbol: Instrument symbol to subscribe to.

        Returns:
            An async iterator yielding :class:`~broker.types.Tick`
            instances as they arrive. Stop consuming (e.g. break out of
            an ``async for`` loop) to unsubscribe.

        Raises:
            core.exceptions.MarketDataError: If the subscription cannot
                be established.
        """

    @abstractmethod
    async def submit_order(self, order: OrderRequest) -> OrderResult:
        """Mechanically submits an order to the broker.

        This performs no risk checks, no position sizing, and no
        strategy validation — it is the broker-facing "send this exact
        order" primitive that later Risk/Execution Engine milestones
        will call after making those decisions.

        Args:
            order: The order to submit.

        Returns:
            The result of the submission — filled, rejected, or
            (for brokers that support it) pending.

        Raises:
            core.exceptions.ExecutionError: If the order cannot be
                submitted at all (as opposed to being rejected by the
                broker, which is reported via ``OrderResult.status``).
        """

    @abstractmethod
    async def get_positions(self) -> list[Position]:
        """Retrieves currently open positions/contracts.

        Raises:
            core.exceptions.BrokerConnectionError: If not connected, or
                the broker call fails.
        """

    @abstractmethod
    async def get_trade_history(self, count: int = 100) -> list[TradeHistoryEntry]:
        """Retrieves recently closed trades, most recent last.

        Args:
            count: Maximum number of trades to retrieve.

        Raises:
            core.exceptions.BrokerConnectionError: If not connected, or
                the broker call fails.
        """

    async def __aenter__(self) -> Self:
        """Connects on entering an ``async with`` block."""
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Disconnects on leaving an ``async with`` block, even on error."""
        await self.disconnect()
