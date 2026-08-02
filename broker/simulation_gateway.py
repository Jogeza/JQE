"""In-memory :class:`~broker.base.BrokerGateway` implementation.

No network access, no external dependency, fully deterministic given a
seed. This is the gateway every other module (market intelligence,
strategy, risk, execution, analytics) should be developed and tested
against by default — it lets the rest of the Quant Core be built and
verified without a live broker connection, a demo account, or network
access at all.

Price generation is a simple seeded random walk. It is intentionally
not realistic market simulation (no volatility regimes, no
microstructure) — that's out of scope for a broker-layer stub. Treat it
as "a source of plausible-shaped OHLC/tick data with a working
connect/order/position lifecycle around it," not as a backtesting
engine.
"""

from __future__ import annotations

import asyncio
import itertools
import random
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone

from broker.base import BrokerGateway
from broker.types import (
    TIMEFRAME_SECONDS,
    AccountInfo,
    Candle,
    OrderRequest,
    OrderResult,
    OrderStatus,
    Position,
    Tick,
    Timeframe,
    TradeHistoryEntry,
)
from core.exceptions import BrokerConnectionError
from core.logger import logger

_DEFAULT_STARTING_PRICE = 100.0
_DEFAULT_SPREAD = 0.02


class SimulationGateway(BrokerGateway):
    """Deterministic, in-memory broker simulation.

    Attributes:
        starting_balance: Simulated starting account balance.
        seed: Seed for the internal random number generator. The same
            seed always produces the same price path for a given
            sequence of calls, so tests built against this gateway are
            reproducible.
    """

    def __init__(self, starting_balance: float = 10_000.0, seed: int | None = 42) -> None:
        self.starting_balance = starting_balance
        self.seed = seed
        self._connected = False
        self._balance = starting_balance
        self._currency = "USD"
        self._rng = random.Random(seed)
        self._prices: dict[str, float] = {}
        self._positions: dict[str, Position] = {}
        self._trade_history: list[TradeHistoryEntry] = []
        self._order_ids = itertools.count(1)

    async def connect(self) -> None:
        """Marks the gateway as connected. Never fails."""
        self._connected = True
        logger.info(
            "SimulationGateway connected (starting_balance={} {})",
            self.starting_balance,
            self._currency,
        )

    async def disconnect(self) -> None:
        """Marks the gateway as disconnected. Never fails."""
        self._connected = False
        logger.info("SimulationGateway disconnected")

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def get_account_info(self) -> AccountInfo:
        self._require_connected()
        return AccountInfo(
            account_id="SIMULATED",
            balance=self._balance,
            currency=self._currency,
            equity=self._balance,
        )

    async def get_candles(self, symbol: str, timeframe: Timeframe, count: int) -> list[Candle]:
        self._require_connected()
        step_seconds = TIMEFRAME_SECONDS[timeframe]
        price = self._price_for(symbol)
        now = datetime.now(timezone.utc)
        candles: list[Candle] = []
        for i in range(count):
            open_price = price
            close_price = max(0.01, open_price + self._rng.uniform(-0.5, 0.5))
            high = max(open_price, close_price) + abs(self._rng.uniform(0, 0.2))
            low = max(0.01, min(open_price, close_price) - abs(self._rng.uniform(0, 0.2)))
            candles.append(
                Candle(
                    time=now - timedelta(seconds=step_seconds * (count - i)),
                    open=open_price,
                    high=high,
                    low=low,
                    close=close_price,
                    volume=self._rng.uniform(10, 100),
                )
            )
            price = close_price
        self._prices[symbol] = price
        return candles

    def stream_ticks(self, symbol: str) -> AsyncIterator[Tick]:
        self._require_connected()
        return self._tick_stream(symbol)

    async def submit_order(self, order: OrderRequest) -> OrderResult:
        self._require_connected()
        price = self._price_for(order.symbol)
        order_id = f"SIM-{next(self._order_ids)}"
        self._positions[order_id] = Position(
            position_id=order_id,
            symbol=order.symbol,
            side=order.side,
            volume=order.volume,
            open_price=price,
            current_price=price,
            profit=0.0,
            stop_loss=order.stop_loss,
            take_profit=order.take_profit,
            opened_at=datetime.now(timezone.utc),
        )
        logger.info(
            "SimulationGateway order filled: {} {} {} @ {:.4f}",
            order.side,
            order.volume,
            order.symbol,
            price,
        )
        return OrderResult(
            order_id=order_id,
            status=OrderStatus.FILLED,
            symbol=order.symbol,
            side=order.side,
            volume=order.volume,
            filled_price=price,
            raw={"simulated": True},
        )

    async def get_positions(self) -> list[Position]:
        self._require_connected()
        return list(self._positions.values())

    async def get_trade_history(self, count: int = 100) -> list[TradeHistoryEntry]:
        self._require_connected()
        return self._trade_history[-count:]

    async def _tick_stream(self, symbol: str) -> AsyncIterator[Tick]:
        """Yields one synthetic tick per iteration for as long as connected."""
        while self._connected:
            price = self._price_for(symbol)
            new_price = max(0.01, price + self._rng.uniform(-0.1, 0.1))
            self._prices[symbol] = new_price
            yield Tick(
                time=datetime.now(timezone.utc),
                symbol=symbol,
                bid=new_price - _DEFAULT_SPREAD / 2,
                ask=new_price + _DEFAULT_SPREAD / 2,
                last=new_price,
            )
            # Yield control to the event loop without a real delay —
            # this is a synthetic feed, not a real-time simulation.
            await asyncio.sleep(0)

    def _price_for(self, symbol: str) -> float:
        return self._prices.setdefault(symbol, _DEFAULT_STARTING_PRICE)

    def _require_connected(self) -> None:
        if not self._connected:
            raise BrokerConnectionError("SimulationGateway is not connected — call connect() first")
