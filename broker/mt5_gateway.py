"""BrokerGateway implementation for MetaTrader 5.

Reuses the existing core MT5 connection and market data layers while
adapting them to the BrokerGateway interface.

The MetaTrader5 Python package is synchronous, so blocking calls are
wrapped with asyncio.to_thread() to keep the gateway async compatible.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

import MetaTrader5 as mt5

from broker.base import BrokerGateway
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
from core.exceptions import (
    BrokerConnectionError,
    ExecutionError,
    MarketDataError,
)
from core.logger import logger
from core.mt5_connection import connect as mt5_connect
from core.mt5_connection import disconnect as mt5_disconnect
from core.mt5_session import mt5_session


_TRADE_HISTORY_LOOKBACK_DAYS = 30
_DEFAULT_TICK_POLL_INTERVAL_SECONDS = 1.0

_MT5_SYMBOL_ALIASES: dict[str, list[str]] = {
    "GOLD": [
        "GOLD",
        "XAUUSD",
        "XAUUSDm",
        "XAUUSD.pro",
        "GOLD#",
    ],
    "BTCUSD": [
        "BTCUSD",
        "BTCUSDm",
        "BTCUSD.pro",
    ],
    "DOW30": [
        "DOW30",
        "US30",
        "DJ30",
        "WS30",
    ],
    "EURUSD": [
        "EURUSD",
        "EURUSDm",
        "EURUSD.pro",
    ],
    "GBPUSD": ["GBPUSD", "GBPUSDm", "GBPUSD.pro"],
    "R_75": ["Volatility 75 Index"],
    "VOLATILITY_75": ["Volatility 75 Index"],
}


def _numeric_attr(value: object, name: str, default: float = 0.0) -> float:
    candidate = getattr(value, name, default)
    return float(candidate) if isinstance(candidate, (int, float)) and not isinstance(candidate, bool) else default


def _normalize_volume(requested: float, symbol_info: object) -> float:
    """Normalize down to the broker step without increasing authorized risk."""
    minimum = _numeric_attr(symbol_info, "volume_min")
    maximum = _numeric_attr(symbol_info, "volume_max")
    step = _numeric_attr(symbol_info, "volume_step")
    if not math.isfinite(requested) or requested <= 0 or minimum <= 0 or maximum < minimum or step <= 0:
        raise ExecutionError("Invalid MT5 volume specification", requested_volume=requested)
    if requested + 1e-12 < minimum:
        raise ExecutionError("MT5 volume is below the symbol minimum", requested_volume=requested, minimum=minimum)
    if requested > maximum + 1e-12:
        raise ExecutionError("MT5 volume exceeds the symbol maximum", requested_volume=requested, maximum=maximum)
    normalized = round(math.floor((requested + 1e-12) / step) * step, 8)
    if normalized + 1e-12 < minimum:
        raise ExecutionError("MT5 normalized volume is below the symbol minimum", requested_volume=requested)
    return normalized


def _select_filling_mode(symbol_info: object) -> int:
    """Translate MT5 symbol filling flags into an allowed order policy."""
    flags = int(_numeric_attr(symbol_info, "filling_mode", -1))
    if flags >= 0 and flags & int(getattr(mt5, "SYMBOL_FILLING_IOC", 2)):
        return mt5.ORDER_FILLING_IOC
    if flags >= 0 and flags & int(getattr(mt5, "SYMBOL_FILLING_FOK", 1)):
        return mt5.ORDER_FILLING_FOK
    if getattr(symbol_info, "trade_exemode", None) != getattr(mt5, "SYMBOL_TRADE_EXECUTION_MARKET", object()):
        return mt5.ORDER_FILLING_RETURN
    raise ExecutionError("MT5 symbol has no supported filling mode")


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
        *,
        terminal_path: Path | None = None,
        login: int | None = None,
        password: str | None = None,
        server: str | None = None,
        expected_environment: str | None = None,
        strict_lifecycle: bool = False,
    ) -> None:
        self._session_owner = object()
        self._pinned_identity: tuple[int, str] | None = None
        self.tick_poll_interval = tick_poll_interval
        self.terminal_path = terminal_path
        self.login = login
        self.password = password
        self.server = server
        self.expected_environment = expected_environment
        self.strict_lifecycle = strict_lifecycle

    def _resolve_symbol(self, symbol: str) -> str | None:
        """Resolves broker-specific symbol using alias priority order."""
        candidates = _MT5_SYMBOL_ALIASES.get(symbol, [symbol])
        for candidate in candidates:
            info = mt5.symbol_info(candidate)
            if info is not None:
                if not getattr(info, "visible", True):
                    mt5.symbol_select(candidate, True)
                logger.info("Symbol mapped: {} -> {}", symbol, candidate)
                return candidate
        logger.error("No broker symbol found for {}", symbol)
        return None

    async def connect(self) -> None:
        await asyncio.to_thread(self._connect_session)

    def _initialize_session(self) -> bool:
        return mt5_connect(
            terminal_path=self.terminal_path,
            login=self.login,
            password=self.password,
            server=self.server,
            _session_owner=self._session_owner,
        )

    def _connect_session(self) -> None:
        with mt5_session.lock:
            if not mt5_session.reserve(self._session_owner):
                raise BrokerConnectionError("MT5 process-global session already owned")
            self._pinned_identity = None
            try:
                if self._initialize_session() is not True:
                    raise BrokerConnectionError("Failed to connect to MT5 terminal")
                if self._verify_connection_identity() is not True:
                    raise BrokerConnectionError("MT5 connection identity verification failed")
                info = mt5.account_info()
                self._pinned_identity = self._identity(info)
                if self._pinned_identity is None or self._is_demo_account(info) is not True:
                    raise BrokerConnectionError("MT5 connection identity unavailable")
                if self._verify_connection_identity() is not True:
                    raise BrokerConnectionError("MT5 connection identity observations conflict")
                mt5_session.activate(self._session_owner)
            except BaseException:
                try:
                    mt5_disconnect()
                finally:
                    mt5_session.invalidate()
                    self._pinned_identity = None
                raise

    @staticmethod
    def _identity(account: object) -> tuple[int, str] | None:
        login = getattr(account, "login", None)
        server = getattr(account, "server", None)
        if type(login) is not int or login <= 0 or type(server) is not str or not server.strip():
            return None
        return login, server

    @staticmethod
    def _is_demo_account(account: object) -> bool:
        mode = getattr(account, "trade_mode", None)
        return type(mode) is int and mode == 0

    def _verify_connection_identity(self, *, require_trading: bool = False) -> bool:
        account = mt5.account_info()
        terminal = mt5.terminal_info()
        if account is None or terminal is None:
            logger.error("MT5 connection health unavailable")
            return False
        if getattr(terminal, "connected", False) is not True:
            logger.error("MT5 terminal is not connected")
            return False
        identity = self._identity(account)
        if identity is None or self._is_demo_account(account) is not True:
            logger.error("MT5 account identity or DEMO verification unavailable")
            return False
        if self._pinned_identity is not None and identity != self._pinned_identity:
            logger.error("MT5 pinned account identity mismatch")
            return False
        if require_trading and (
            getattr(terminal, "trade_allowed", False) is not True
            or getattr(terminal, "tradeapi_disabled", False) is True
        ):
            logger.error("MT5 trading is disabled")
            return False
        if self.login is not None and identity[0] != self.login:
            logger.error("MT5 account identity mismatch")
            return False
        if self.server is not None and identity[1] != self.server:
            logger.error("MT5 server identity mismatch")
            return False
        if self.expected_environment is not None:
            observed = "demo" if self._is_demo_account(account) is True else None
            if observed != self.expected_environment:
                logger.error("MT5 environment mismatch: expected {} observed {}", self.expected_environment, observed)
                return False
        elif self.strict_lifecycle:
            logger.error("MT5 expected environment is not configured")
            return False
        return True

    async def disconnect(self) -> None:
        await asyncio.to_thread(self._disconnect_session)

    def _disconnect_session(self) -> None:
        with mt5_session.lock:
            if not mt5_session.owns(self._session_owner):
                return
            try:
                mt5_disconnect()
            finally:
                mt5_session.invalidate()
                self._pinned_identity = None

    @property
    def _connected(self) -> bool:
        return mt5_session.is_active(self._session_owner)

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def get_account_info(self) -> AccountInfo:
        return await asyncio.to_thread(self._read_account_info)

    def _read_account_info(self) -> AccountInfo:
        with mt5_session.lock:
            return self._read_verified_account_info()

    def _read_verified_account_info(self) -> AccountInfo:
        self._require_connected()
        info = mt5.account_info()

        if info is None:
            mt5_session.deactivate(self._session_owner)
            raise BrokerConnectionError(
                "Failed to retrieve MT5 account info"
            )
        if (
            self._pinned_identity is None
            or self._identity(info) != self._pinned_identity
            or self._is_demo_account(info) is not True
            or self._verify_connection_identity() is not True
        ):
            mt5_session.deactivate(self._session_owner)
            raise BrokerConnectionError("MT5 pinned account identity or DEMO verification failed")

        return AccountInfo(
            account_id=str(info.login),
            balance=float(info.balance),
            currency=str(info.currency),
            equity=float(info.equity),
            leverage=float(info.leverage),
            server=str(info.server),
            trade_mode="demo",
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
            real_symbol = self._resolve_symbol(symbol)
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
                    source="mt5",
                )
                for rate in raw_rates
            ]

        real_symbol = self._resolve_symbol(symbol)
        if not real_symbol:
            raise MarketDataError("Unknown MT5 symbol", symbol=symbol)

        raw_rates = await asyncio.to_thread(
            mt5.copy_rates_from_pos,
            real_symbol,
            _mt5_timeframe(timeframe),
            0,
            count,
        )

        if raw_rates is None or len(raw_rates) == 0:
            raise MarketDataError(
                "No candle data returned from MT5",
                symbol=symbol,
            )

        return [
            Candle(
                time=datetime.fromtimestamp(rate["time"], tz=timezone.utc),
                open=float(rate["open"]),
                high=float(rate["high"]),
                low=float(rate["low"]),
                close=float(rate["close"]),
                volume=(
                    float(rate["tick_volume"])
                    if not isinstance(rate, dict) or "tick_volume" in rate
                    else None
                ),
                source="mt5",
            )
            for rate in raw_rates
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
        from broker.types import ExecutionQuantityUnit
        if order.quantity.unit is not ExecutionQuantityUnit.MT5_LOTS:
            raise ExecutionError("MT5 requires MT5_LOTS")
        requested_quantity = order.quantity.value
        if self.strict_lifecycle or self.expected_environment or self.login is not None or self.server is not None:
            if await asyncio.to_thread(self._verify_connection_identity, require_trading=True) is not True:
                mt5_session.deactivate(self._session_owner)
                raise BrokerConnectionError("MT5 pre-submit readiness verification failed")

        real_symbol = self._resolve_symbol(
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

        if getattr(symbol_info, "trade_mode", None) == getattr(mt5, "SYMBOL_TRADE_MODE_DISABLED", 0):
            raise ExecutionError("MT5 symbol is disabled", symbol=order.symbol)
        quantity = _normalize_volume(requested_quantity, symbol_info)

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

        market_price = round(tick.ask if order.side is OrderSide.BUY else tick.bid, digits)
        price = round(order.entry_price, digits) if order.entry_price is not None else market_price
        minimum_distance = symbol_info.trade_stops_level * point
        stop_loss = round(order.stop_loss, digits)
        take_profit = round(order.take_profit, digits) if order.take_profit is not None else None

        if order.order_type is not OrderType.MARKET:
            trigger_distance = (
                price - round(float(tick.ask), digits)
                if order.side is OrderSide.BUY
                else round(float(tick.bid), digits) - price
            )
            if trigger_distance < minimum_distance:
                raise ExecutionError("MT5 pending trigger validation failed", symbol=order.symbol)

        stop_limit_price = None
        if order.order_type is OrderType.STOP_LIMIT:
            stop_limit_price = round(float(order.stop_limit_price), digits)
            if order.side is OrderSide.BUY and stop_limit_price > price:
                raise ExecutionError("MT5 buy stop-limit price must not exceed its trigger", symbol=order.symbol)
            if order.side is OrderSide.SELL and stop_limit_price < price:
                raise ExecutionError("MT5 sell stop-limit price must not be below its trigger", symbol=order.symbol)

        if order.side is OrderSide.BUY:
            if price - stop_loss < minimum_distance:
                raise ExecutionError("MT5 stop-loss validation failed", symbol=order.symbol)
            if take_profit is not None and take_profit - price < minimum_distance:
                raise ExecutionError("MT5 take-profit validation failed", symbol=order.symbol)
        else:
            if stop_loss - price < minimum_distance:
                raise ExecutionError("MT5 stop-loss validation failed", symbol=order.symbol)
            if take_profit is not None and price - take_profit < minimum_distance:
                raise ExecutionError("MT5 take-profit validation failed", symbol=order.symbol)

        native_type = {
            OrderType.MARKET: mt5.ORDER_TYPE_BUY if order.side is OrderSide.BUY else mt5.ORDER_TYPE_SELL,
            OrderType.BUY_STOP: mt5.ORDER_TYPE_BUY_STOP,
            OrderType.SELL_STOP: mt5.ORDER_TYPE_SELL_STOP,
            OrderType.STOP_LIMIT: mt5.ORDER_TYPE_BUY_STOP_LIMIT if order.side is OrderSide.BUY else mt5.ORDER_TYPE_SELL_STOP_LIMIT,
        }[order.order_type]
        request = {
            "action": mt5.TRADE_ACTION_DEAL if order.order_type is OrderType.MARKET else mt5.TRADE_ACTION_PENDING,
            "symbol": real_symbol,
            "volume": quantity,
            "type": native_type,
            "price": price,
            "sl": stop_loss,
            "tp": take_profit or 0.0,
            "deviation": 20,
            "magic": order.magic_number or 20260802,
            "comment": order.order_comment or "JQE Gateway Execution",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": _select_filling_mode(symbol_info) if order.order_type is OrderType.MARKET else mt5.ORDER_FILLING_RETURN,
        }
        if stop_limit_price is not None:
            request["stoplimit"] = stop_limit_price

        logger.info(
            "MT5 order request: {}",
            request,
        )

        check = await asyncio.to_thread(mt5.order_check, request)
        if check is None or getattr(check, "retcode", None) != 0:
            raise ExecutionError(
                "MT5 order_check rejected request", symbol=order.symbol,
                retcode=getattr(check, "retcode", None),
                comment=getattr(check, "comment", ""), request=request,
            )

        result = await asyncio.to_thread(
            mt5.order_send,
            request,
        )

        if result is None or getattr(result, "retcode", None) is None:
            raise ExecutionError(
                "MT5 order outcome is indeterminate",
                symbol=order.symbol,
                request=request,
            )

        accepted_retcodes = {mt5.TRADE_RETCODE_DONE}
        if order.order_type is not OrderType.MARKET:
            accepted_retcodes.add(mt5.TRADE_RETCODE_PLACED)
        if result.retcode not in accepted_retcodes:

            return OrderResult(
                order_id="",
                status=OrderStatus.REJECTED,
                symbol=order.symbol,
                side=order.side,
                volume=quantity,
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
                    "order": getattr(result, "order", None),
                    "deal": getattr(result, "deal", None),
                    "request": request,
                },
            )

        result_order = getattr(result, "order", None) or getattr(result, "deal", None)
        result_price = getattr(result, "price", None)
        if result_order in (None, "") or (
            order.order_type is OrderType.MARKET
            and (not isinstance(result_price, (int, float)) or isinstance(result_price, bool))
        ):
            raise ExecutionError("MT5 successful response lacked execution evidence", symbol=order.symbol, retcode=result.retcode)

        return OrderResult(
            order_id=str(result_order),
            status=OrderStatus.FILLED if order.order_type is OrderType.MARKET else OrderStatus.SUBMITTED,
            symbol=order.symbol,
            side=order.side,
            volume=quantity,
            filled_price=float(result_price) if order.order_type is OrderType.MARKET else None,
            raw={
                "retcode": result.retcode,
                "comment": getattr(result, "comment", ""),
                "deal": getattr(result, "deal", None),
                "position": getattr(result, "position", None),
                "requested_volume": requested_quantity,
                "filled_volume": _numeric_attr(result, "volume", quantity),
                "requested_price": price,
                "order_type": order.order_type.value,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "stop_limit_price": stop_limit_price,
                "request": request,
            },
        )

    async def close_position(self, position_id: str, *, volume: float | None = None) -> OrderResult:
        """Close an authoritative MT5 position by ticket and confirm final state."""
        self._require_connected()
        if await asyncio.to_thread(self._verify_connection_identity, require_trading=True) is not True:
            mt5_session.deactivate(self._session_owner)
            raise BrokerConnectionError("MT5 pre-close readiness verification failed")
        try:
            ticket = int(position_id)
        except (TypeError, ValueError) as exc:
            raise ExecutionError("Invalid MT5 position ticket", position_id=position_id) from exc
        native = await asyncio.to_thread(mt5.positions_get, ticket=ticket)
        if not native:
            raise ExecutionError("MT5 position was not found", position_id=position_id)
        position = native[0]
        info = await asyncio.to_thread(mt5.symbol_info, position.symbol)
        tick = await asyncio.to_thread(mt5.symbol_info_tick, position.symbol)
        if info is None or tick is None:
            raise ExecutionError("MT5 close preflight data is unavailable", position_id=position_id)
        close_volume = _normalize_volume(float(volume if volume is not None else position.volume), info)
        is_buy = position.type == mt5.ORDER_TYPE_BUY
        price = round(float(tick.bid if is_buy else tick.ask), int(info.digits))
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": position.symbol,
            "position": ticket,
            "volume": close_volume,
            "type": mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY,
            "price": price,
            "deviation": 20,
            "magic": int(getattr(position, "magic", 20260802) or 20260802),
            "comment": "JQE position close",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": _select_filling_mode(info),
        }
        check = await asyncio.to_thread(mt5.order_check, request)
        if check is None or getattr(check, "retcode", None) != 0:
            raise ExecutionError("MT5 close order_check rejected request", retcode=getattr(check, "retcode", None), comment=getattr(check, "comment", ""), request=request)
        result = await asyncio.to_thread(mt5.order_send, request)
        if result is None or getattr(result, "retcode", None) != mt5.TRADE_RETCODE_DONE:
            raise ExecutionError("MT5 close order_send rejected request", retcode=getattr(result, "retcode", None), comment=getattr(result, "comment", ""), request=request)
        remaining = await asyncio.to_thread(mt5.positions_get, ticket=ticket)
        if remaining and close_volume + 1e-12 >= float(position.volume):
            raise ExecutionError("MT5 reported success but position remains open", position_id=position_id)
        return OrderResult(
            order_id=str(getattr(result, "order", None) or getattr(result, "deal", "")),
            status=OrderStatus.FILLED,
            symbol=position.symbol,
            side=OrderSide.SELL if is_buy else OrderSide.BUY,
            volume=close_volume,
            filled_price=float(getattr(result, "price", price)),
            raw={"retcode": result.retcode, "deal": getattr(result, "deal", None), "position": ticket, "request": request},
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
                magic=(
                    int(p.magic)
                    if getattr(p, "magic", None) is not None
                    else None
                ),
                comment=(
                    str(p.comment)
                    if getattr(p, "comment", None) is not None
                    else None
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

        real_symbol = self._resolve_symbol(
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
