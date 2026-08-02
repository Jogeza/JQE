"""``BrokerGateway`` implementation for MetaTrader 5.

Reuses the existing :func:`core.mt5_connection.connect`/:func:`~core.
mt5_connection.disconnect` and :class:`core.market_data.MarketData`
rather than reimplementing MT5 session/candle handling — this is the
same logic Milestone 1 already hardened with config/logging/exceptions,
just adapted to the gateway interface (per "adapt the existing
repository instead of destroying working components").

The ``MetaTrader5`` package's Python bindings are synchronous
(blocking C-extension calls) with no native async support, so every
call here is wrapped in :func:`asyncio.to_thread` to fit
:class:`~broker.base.BrokerGateway`'s async interface without blocking
the event loop.
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
from core.exceptions import BrokerConnectionError, ExecutionError, MarketDataError
from core.logger import logger
from core.market_data import MarketData
from core.mt5_connection import connect as mt5_connect
from core.mt5_connection import disconnect as mt5_disconnect

_TRADE_HISTORY_LOOKBACK_DAYS = 30
_DEFAULT_TICK_POLL_INTERVAL_SECONDS = 1.0


class MT5Gateway(BrokerGateway):
    """``BrokerGateway`` implementation backed by a local MT5 terminal.

    Attributes:
        tick_poll_interval: Seconds between polls in :meth:`stream_ticks`.
            MT5's Python API has no native tick-push subscription, so
            ticks are polled — this is a documented limitation, not an
            oversight; a push-based feed would require the MT5 terminal's
            event system, which the ``MetaTrader5`` package doesn't expose.
    """

    def __init__(self, tick_poll_interval: float = _DEFAULT_TICK_POLL_INTERVAL_SECONDS) -> None:
        self._market_data = MarketData()
        self._connected = False
        self.tick_poll_interval = tick_poll_interval

    async def connect(self) -> None:
        connected = await asyncio.to_thread(mt5_connect)
        if not connected:
            raise BrokerConnectionError("Failed to connect to MT5 terminal")
        self._connected = True

    async def disconnect(self) -> None:
        await asyncio.to_thread(mt5_disconnect)
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def get_account_info(self) -> AccountInfo:
        self._require_connected()
        info = await asyncio.to_thread(mt5.account_info)
        if info is None:
            raise BrokerConnectionError("Failed to retrieve MT5 account info")
        return AccountInfo(
            account_id=str(info.login),
            balance=float(info.balance),
            currency=str(info.currency),
            equity=float(info.equity),
            leverage=float(info.leverage),
        )

    async def get_candles(self, symbol: str, timeframe: Timeframe, count: int) -> list[Candle]:
        self._require_connected()
        # NOTE: MarketData currently fetches on a fixed internal
        # timeframe (H1) and does not yet accept `timeframe` — see
        # docs/roadmap.md. Accepted here for interface conformance.
        del timeframe
        raw_candles = await asyncio.to_thread(self._market_data.get_candles, symbol, count)
        if not raw_candles:
            raise MarketDataError("No candle data returned from MT5", symbol=symbol)
        return [
            Candle(
                time=candle["time"],
                open=float(candle["open"]),
                high=float(candle["high"]),
                low=float(candle["low"]),
                close=float(candle["close"]),
                volume=float(candle.get("volume", 0.0)),
            )
            for candle in raw_candles
        ]

    def stream_ticks(self, symbol: str) -> AsyncIterator[Tick]:
        self._require_connected()
        return self._tick_stream(symbol)

    async def submit_order(self, order: OrderRequest) -> OrderResult:
        self._require_connected()
        real_symbol = self._market_data.resolve_symbol(order.symbol)
        if not real_symbol:
            raise ExecutionError("Unknown MT5 symbol", symbol=order.symbol)

        tick = await asyncio.to_thread(mt5.symbol_info_tick, real_symbol)
        if tick is None:
            raise MarketDataError("No tick data available to price order", symbol=order.symbol)

        price = tick.ask if order.side is OrderSide.BUY else tick.bid
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": real_symbol,
            "volume": order.volume,
            "type": mt5.ORDER_TYPE_BUY if order.side is OrderSide.BUY else mt5.ORDER_TYPE_SELL,
            "price": price,
            "sl": order.stop_loss or 0.0,
            "tp": order.take_profit or 0.0,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = await asyncio.to_thread(mt5.order_send, request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            retcode = getattr(result, "retcode", None)
            logger.warning(
                "MT5Gateway order rejected: {} {} {} retcode={}",
                order.side,
                order.volume,
                order.symbol,
                retcode,
            )
            return OrderResult(
                order_id="",
                status=OrderStatus.REJECTED,
                symbol=order.symbol,
                side=order.side,
                volume=order.volume,
                raw={"retcode": retcode},
            )

        logger.info(
            "MT5Gateway order filled: {} {} {} order={}",
            order.side,
            order.volume,
            order.symbol,
            result.order,
        )
        return OrderResult(
            order_id=str(result.order),
            status=OrderStatus.FILLED,
            symbol=order.symbol,
            side=order.side,
            volume=order.volume,
            filled_price=float(result.price),
            raw={"retcode": result.retcode},
        )

    async def get_positions(self) -> list[Position]:
        self._require_connected()
        raw_positions = await asyncio.to_thread(mt5.positions_get)
        if not raw_positions:
            return []
        return [
            Position(
                position_id=str(p.ticket),
                symbol=p.symbol,
                side=OrderSide.BUY if p.type == mt5.ORDER_TYPE_BUY else OrderSide.SELL,
                volume=float(p.volume),
                open_price=float(p.price_open),
                current_price=float(p.price_current),
                profit=float(p.profit),
                stop_loss=float(p.sl) or None,
                take_profit=float(p.tp) or None,
                opened_at=datetime.fromtimestamp(p.time, tz=timezone.utc),
            )
            for p in raw_positions
        ]

    async def get_trade_history(self, count: int = 100) -> list[TradeHistoryEntry]:
        self._require_connected()
        now = datetime.now(timezone.utc)
        from_date = now - timedelta(days=_TRADE_HISTORY_LOOKBACK_DAYS)
        deals = await asyncio.to_thread(mt5.history_deals_get, from_date, now)
        if not deals:
            return []

        # NOTE: approximated from the closing ("out") deal only — MT5's
        # raw deal history requires pairing entry/exit deals by
        # position_id for an exact open price. That pairing is deferred;
        # see docs/roadmap.md.
        closing_deals = [deal for deal in deals if deal.entry == mt5.DEAL_ENTRY_OUT]
        entries = [
            TradeHistoryEntry(
                trade_id=str(deal.position_id),
                symbol=deal.symbol,
                side=OrderSide.SELL if deal.type == mt5.DEAL_TYPE_BUY else OrderSide.BUY,
                volume=float(deal.volume),
                open_price=float(deal.price),
                close_price=float(deal.price),
                profit=float(deal.profit),
                opened_at=datetime.fromtimestamp(deal.time, tz=timezone.utc),
                closed_at=datetime.fromtimestamp(deal.time, tz=timezone.utc),
            )
            for deal in closing_deals[-count:]
        ]
        return entries

    async def _tick_stream(self, symbol: str) -> AsyncIterator[Tick]:
        real_symbol = self._market_data.resolve_symbol(symbol)
        if not real_symbol:
            raise MarketDataError("Unknown MT5 symbol", symbol=symbol)
        while self._connected:
            tick = await asyncio.to_thread(mt5.symbol_info_tick, real_symbol)
            if tick is not None:
                yield Tick(
                    time=datetime.fromtimestamp(tick.time, tz=timezone.utc),
                    symbol=symbol,
                    bid=float(tick.bid),
                    ask=float(tick.ask),
                    last=float(tick.last) if tick.last else None,
                )
            await asyncio.sleep(self.tick_poll_interval)

    def _require_connected(self) -> None:
        if not self._connected:
            raise BrokerConnectionError("MT5Gateway is not connected — call connect() first")
