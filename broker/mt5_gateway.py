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


#: Maps the broker-agnostic Timeframe to MT5's native constants. Built
#: lazily (not at module import time) since `mt5` is a MagicMock stub
#: outside a real MT5 environment (see tests/conftest.py) — its
#: TIMEFRAME_* attributes only exist meaningfully once the real SDK is
#: importable.
def _mt5_timeframe(timeframe: Timeframe) -> int:
    mapping = {
        Timeframe.M1: mt5.TIMEFRAME_M1,
        Timeframe.M5: mt5.TIMEFRAME_M5,
        Timeframe.M15: mt5.TIMEFRAME_M15,
        Timeframe.M30: mt5.TIMEFRAME_M30,
        Timeframe.H1: mt5.TIMEFRAME_H1,
        Timeframe.H4: mt5.TIMEFRAME_H4,
        Timeframe.D1: mt5.TIMEFRAME_D1,
    }
    return mapping[timeframe]


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
        self, symbol: str, timeframe: Timeframe, count: int, end: datetime | None = None
    ) -> list[Candle]:
        self._require_connected()

        if end is not None:
            # Historical range query — no existing wrapper for this in
            # core.market_data, so call the SDK directly (same pattern
            # as submit_order/get_positions/get_trade_history below).
            # NOT verified against a live terminal — see module
            # docstring; mt5.copy_rates_from's exact date-anchoring
            # semantics should be confirmed against a demo account
            # before relying on this for precise gap-filling.
            real_symbol = self._market_data.resolve_symbol(symbol)
            if not real_symbol:
                raise MarketDataError("Unknown MT5 symbol", symbol=symbol)
            raw_rates = await asyncio.to_thread(
                mt5.copy_rates_from, real_symbol, _mt5_timeframe(timeframe), end, count
            )
            if raw_rates is None or len(raw_rates) == 0:
                raise MarketDataError("No candle data returned from MT5", symbol=symbol)
            return [
                Candle(
                    time=datetime.fromtimestamp(rate["time"], tz=timezone.utc),
                    open=float(rate["open"]),
                    high=float(rate["high"]),
                    low=float(rate["low"]),
                    close=float(rate["close"]),
                    volume=float(rate["tick_volume"]),
                )
                for rate in raw_rates
            ]

        # NOTE: MarketData currently fetches on a fixed internal
        # timeframe (H1) and does not yet accept `timeframe` — see
        # docs/roadmap.md. Accepted here for interface conformance.
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

        # Filter to closing executions only.
        #
        # MT5 history_deals_get returns ALL deal types:
        #   DEAL_ENTRY_IN    — position-opening deals (profit ≈ 0, not a close)
        #   DEAL_ENTRY_OUT   — position-closing deals (carries realized P/L)
        #   DEAL_ENTRY_INOUT — reversal deals (closing P/L in same deal)
        # Non-execution accounting entries also appear:
        #   DEAL_TYPE_COMMISSION — broker commission charge
        #   DEAL_TYPE_INTEREST   — swap/overnight interest
        #   DEAL_TYPE_BALANCE    — deposit/withdrawal adjustment
        #   DEAL_TYPE_CREDIT     — credit adjustment
        #   DEAL_TYPE_BONUS      — bonus credit
        #
        # For daily risk reconciliation we need only closing executions:
        # they are the records that carry realized P/L and represent a
        # completed trading event. DEAL_ENTRY_IN deals have profit ≈ 0
        # and would double-count every position. Commission and interest
        # deals are accounting entries, not trade executions.
        closing_entry_types = {mt5.DEAL_ENTRY_OUT, mt5.DEAL_ENTRY_INOUT}
        non_trade_types = {
            mt5.DEAL_TYPE_COMMISSION,
            mt5.DEAL_TYPE_INTEREST,
            mt5.DEAL_TYPE_BALANCE,
            mt5.DEAL_TYPE_CREDIT,
            mt5.DEAL_TYPE_BONUS,
        }

        closing_deals = [
            d for d in deals
            if d.entry in closing_entry_types and d.type not in non_trade_types
        ]

        return [
            TradeHistoryEntry(
                # deal.ticket is the unique ID for this specific deal record;
                # each partial close gets its own ticket.  deal.position_id
                # is shared by all deals for the same position and must NOT
                # be used here — it conflates opening and closing records.
                trade_id=str(deal.ticket),
                symbol=deal.symbol,
                side=(
                    OrderSide.SELL
                    if deal.type == mt5.DEAL_TYPE_BUY
                    else OrderSide.BUY
                ),
                volume=float(deal.volume),
                # A closing deal does not carry the original entry price.
                # Recovering it would require joining against the opening
                # deal via position_id — deferred as a future improvement.
                # open_price is not consumed by reconciliation logic, so
                # we use the closing execution price in both fields.
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
            for deal in closing_deals[-count:]
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