"""BrokerGateway implementation for MetaTrader 5.

Reuses the existing core MT5 connection and market data layers while
adapting them to the BrokerGateway interface.

The MetaTrader5 Python package is synchronous, so blocking calls are
wrapped with asyncio.to_thread() to keep the gateway async compatible.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone

import MetaTrader5 as mt5

from broker.base import BrokerGateway
from broker.types import (
    AccountInfo,
    Candle,
    OrderRequest,
    OrderResult,
    OrderSide,
    OrderStatus,
    Position,
    Tick,
    Timeframe,
    TradeHistoryEntry,
)
from core.exceptions import (
    BrokerConnectionError,
    ExecutionError,
    MarketDataError,
)
from core.logger import logger
from core.market_data import MarketData
from core.mt5_connection import connect as mt5_connect
from core.mt5_connection import disconnect as mt5_disconnect


_TRADE_HISTORY_LOOKBACK_DAYS = 30
_DEFAULT_TICK_POLL_INTERVAL_SECONDS = 1.0


class MT5Gateway(BrokerGateway):
    """MetaTrader 5 implementation of BrokerGateway."""

    def __init__(
        self,
        tick_poll_interval: float = _DEFAULT_TICK_POLL_INTERVAL_SECONDS,
    ) -> None:
        self._market_data = MarketData()
        self._connected = False
        self.tick_poll_interval = tick_poll_interval

    async def connect(self) -> None:
        connected = await asyncio.to_thread(mt5_connect)

        if not connected:
            raise BrokerConnectionError(
                "Failed to connect to MT5 terminal"
            )

        self._connected = True

    async def disconnect(self) -> None:
        await asyncio.to_thread(mt5_disconnect)
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def get_account_info(self) -> AccountInfo:
        self._require_connected()

        info = await asyncio.to_thread(
            mt5.account_info
        )

        if info is None:
            raise BrokerConnectionError(
                "Failed to retrieve MT5 account info"
            )

        return AccountInfo(
            account_id=str(info.login),
            balance=float(info.balance),
            currency=str(info.currency),
            equity=float(info.equity),
            leverage=float(info.leverage),
        )

    async def get_candles(
        self,
        symbol: str,
        timeframe: Timeframe,
        count: int,
    ) -> list[Candle]:

        self._require_connected()

        del timeframe

        raw_candles = await asyncio.to_thread(
            self._market_data.get_candles,
            symbol,
            count,
        )

        if not raw_candles:
            raise MarketDataError(
                "No candle data returned from MT5",
                symbol=symbol,
            )

        return [
            Candle(
                time=candle["time"],
                open=float(candle["open"]),
                high=float(candle["high"]),
                low=float(candle["low"]),
                close=float(candle["close"]),
                volume=float(
                    candle.get("volume", 0.0)
                ),
            )
            for candle in raw_candles
        ]

    def stream_ticks(
        self,
        symbol: str,
    ) -> AsyncIterator[Tick]:

        self._require_connected()

        return self._tick_stream(symbol)

    async def submit_order(
        self,
        order: OrderRequest,
    ) -> OrderResult:

        self._require_connected()

        real_symbol = self._market_data.resolve_symbol(
            order.symbol
        )

        if not real_symbol:
            raise ExecutionError(
                "Unknown MT5 symbol",
                symbol=order.symbol,
            )

        selected = await asyncio.to_thread(
            mt5.symbol_select,
            real_symbol,
            True,
        )

        if not selected:
            raise MarketDataError(
                "Unable to select MT5 symbol",
                symbol=order.symbol,
            )

        symbol_info = await asyncio.to_thread(
            mt5.symbol_info,
            real_symbol,
        )

        if symbol_info is None:
            raise MarketDataError(
                "Unable to retrieve symbol info",
                symbol=order.symbol,
            )

        tick = await asyncio.to_thread(
            mt5.symbol_info_tick,
            real_symbol,
        )

        if tick is None:
            raise MarketDataError(
                "No tick data available",
                symbol=order.symbol,
            )

        digits = symbol_info.digits
        point = symbol_info.point

        price = (
            tick.ask
            if order.side is OrderSide.BUY
            else tick.bid
        )

        price = round(price, digits)

        minimum_distance = (
            symbol_info.trade_stops_level * point
        )

        stop_loss = order.stop_loss
        take_profit = order.take_profit

        if order.side is OrderSide.BUY:

            if stop_loss:
                stop_loss = round(
                    stop_loss,
                    digits,
                )

                if (
                    price - stop_loss
                    < minimum_distance
                ):
                    stop_loss = round(
                        price - minimum_distance,
                        digits,
                    )

            if take_profit:
                take_profit = round(
                    take_profit,
                    digits,
                )

                if (
                    take_profit - price
                    < minimum_distance
                ):
                    take_profit = round(
                        price + minimum_distance,
                        digits,
                    )

        else:

            if stop_loss:
                stop_loss = round(
                    stop_loss,
                    digits,
                )

                if (
                    stop_loss - price
                    < minimum_distance
                ):
                    stop_loss = round(
                        price + minimum_distance,
                        digits,
                    )

            if take_profit:
                take_profit = round(
                    take_profit,
                    digits,
                )

                if (
                    price - take_profit
                    < minimum_distance
                ):
                    take_profit = round(
                        price - minimum_distance,
                        digits,
                    )

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": real_symbol,
            "volume": order.volume,
            "type": (
                mt5.ORDER_TYPE_BUY
                if order.side is OrderSide.BUY
                else mt5.ORDER_TYPE_SELL
            ),
            "price": price,
            "sl": stop_loss or 0.0,
            "tp": take_profit or 0.0,
            "deviation": 20,
            "magic": 20260802,
            "comment": "JQE Gateway Execution",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        logger.info(
            "MT5 order request: {}",
            request,
        )

        result = await asyncio.to_thread(
            mt5.order_send,
            request,
        )

        if (
            result is None
            or result.retcode
            != mt5.TRADE_RETCODE_DONE
        ):

            return OrderResult(
                order_id="",
                status=OrderStatus.REJECTED,
                symbol=order.symbol,
                side=order.side,
                volume=order.volume,
                raw={
                    "retcode": getattr(
                        result,
                        "retcode",
                        None,
                    ),
                    "comment": getattr(
                        result,
                        "comment",
                        "",
                    ),
                    "request": request,
                },
            )

        return OrderResult(
            order_id=str(result.order),
            status=OrderStatus.FILLED,
            symbol=order.symbol,
            side=order.side,
            volume=order.volume,
            filled_price=float(result.price),
            raw={
                "retcode": result.retcode,
                "request": request,
            },
        )

    async def get_positions(self) -> list[Position]:

        self._require_connected()

        positions = await asyncio.to_thread(
            mt5.positions_get
        )

        if not positions:
            return []

        return [
            Position(
                position_id=str(p.ticket),
                symbol=p.symbol,
                side=(
                    OrderSide.BUY
                    if p.type == mt5.ORDER_TYPE_BUY
                    else OrderSide.SELL
                ),
                volume=float(p.volume),
                open_price=float(p.price_open),
                current_price=float(p.price_current),
                profit=float(p.profit),
                stop_loss=float(p.sl) or None,
                take_profit=float(p.tp) or None,
                opened_at=datetime.fromtimestamp(
                    p.time,
                    tz=timezone.utc,
                ),
            )
            for p in positions
        ]

    async def get_trade_history(
        self,
        count: int = 100,
    ) -> list[TradeHistoryEntry]:

        self._require_connected()

        now = datetime.now(timezone.utc)

        deals = await asyncio.to_thread(
            mt5.history_deals_get,
            now - timedelta(
                days=_TRADE_HISTORY_LOOKBACK_DAYS
            ),
            now,
        )

        if not deals:
            return []

        return [
            TradeHistoryEntry(
                trade_id=str(deal.position_id),
                symbol=deal.symbol,
                side=(
                    OrderSide.SELL
                    if deal.type == mt5.DEAL_TYPE_BUY
                    else OrderSide.BUY
                ),
                volume=float(deal.volume),
                open_price=float(deal.price),
                close_price=float(deal.price),
                profit=float(deal.profit),
                opened_at=datetime.fromtimestamp(
                    deal.time,
                    tz=timezone.utc,
                ),
                closed_at=datetime.fromtimestamp(
                    deal.time,
                    tz=timezone.utc,
                ),
            )
            for deal in deals[-count:]
        ]

    async def _tick_stream(
        self,
        symbol: str,
    ) -> AsyncIterator[Tick]:

        real_symbol = self._market_data.resolve_symbol(
            symbol
        )

        if not real_symbol:
            raise MarketDataError(
                "Unknown MT5 symbol",
                symbol=symbol,
            )

        while self._connected:

            tick = await asyncio.to_thread(
                mt5.symbol_info_tick,
                real_symbol,
            )

            if tick:
                yield Tick(
                    time=datetime.fromtimestamp(
                        tick.time,
                        tz=timezone.utc,
                    ),
                    symbol=symbol,
                    bid=float(tick.bid),
                    ask=float(tick.ask),
                    last=(
                        float(tick.last)
                        if tick.last
                        else None
                    ),
                )

            await asyncio.sleep(
                self.tick_poll_interval
            )

    def _require_connected(self) -> None:

        if not self._connected:
            raise BrokerConnectionError(
                "MT5Gateway is not connected — call connect() first"
            )