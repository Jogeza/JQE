"""``BrokerGateway`` implementation for the Deriv WebSocket API.

Deriv's public API (https://developers.deriv.com) is a single
persistent WebSocket connection carrying JSON request/response
messages (correlated by a caller-supplied ``req_id``) interleaved with
subscription push messages (ticks, ...). This module:

* Maintains one connection and one background reader task
  (:meth:`DerivGateway._read_loop`) that demultiplexes incoming
  messages to either a pending request's future (by ``req_id``) or a
  live subscription's queue (by symbol) — required because a single
  socket is shared between ordinary request/response calls and
  long-lived tick subscriptions.
* Never logs or embeds the API token — it's passed in at construction
  time from :data:`config.settings`, sourced from the environment.

.. important::
    This implementation is written against Deriv's documented request
    shapes (https://developers.deriv.com/docs/) but has **not** been
    exercised against a live/demo Deriv account — this sandbox has no
    network access to Deriv's servers. Treat it as correct-by-design
    and unit-tested against a mocked connection, not integration-
    verified. See "Remaining technical debt" in docs/architecture.md.

    In particular, :meth:`submit_order` maps the broker-agnostic
    ``OrderRequest`` onto Deriv's **Multipliers** contract type
    (``MULTUP``/``MULTDOWN``), the closest Deriv product to a
    directional position with stop-loss/take-profit — a real
    integration test against a demo account is needed to confirm the
    exact parameter names/values (particularly ``multiplier``, which
    is currently a fixed placeholder) before this is used for anything
    beyond development.
"""

from __future__ import annotations

import asyncio
import itertools
import json
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any

import websockets

from broker.base import BrokerGateway
from broker.types import (
    TIMEFRAME_SECONDS,
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
    BrokerAuthenticationError,
    BrokerConnectionError,
    ExecutionError,
    MarketDataError,
)
from core.logger import logger

DEFAULT_ENDPOINT = "wss://ws.derivws.com/websockets/v3"
_REQUEST_TIMEOUT_SECONDS = 15.0
_MULTIPLIER = 100  # NOTE: fixed placeholder — see module docstring.


class DerivGateway(BrokerGateway):
    """``BrokerGateway`` implementation backed by the Deriv WebSocket API.

    Attributes:
        api_token: Deriv API token. Read from configuration
            (``settings.deriv_api_token``), never hardcoded — see
            :func:`broker.factory.get_gateway`.
        app_id: Deriv application ID.
        endpoint: WebSocket endpoint URL (without the ``app_id`` query
            parameter, which is appended automatically).
    """

    def __init__(
        self,
        api_token: str,
        app_id: str,
        endpoint: str = DEFAULT_ENDPOINT,
        request_timeout: float = _REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        if not api_token:
            raise BrokerAuthenticationError("Deriv API token is required")
        self.api_token = api_token
        self.app_id = app_id
        self.endpoint = endpoint
        self._request_timeout = request_timeout

        self._connection: websockets.ClientConnection | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._connected = False
        self._request_ids = itertools.count(1)
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._tick_queues: dict[str, asyncio.Queue[dict[str, Any]]] = {}
        self._account_id: str | None = None
        self._currency: str | None = None

    async def connect(self) -> None:
        url = f"{self.endpoint}?app_id={self.app_id}"
        try:
            self._connection = await websockets.connect(url)
        except Exception as exc:
            raise BrokerConnectionError(
                "Failed to connect to Deriv WebSocket API", endpoint=self.endpoint
            ) from exc

        self._reader_task = asyncio.create_task(self._read_loop())

        response = await self._request({"authorize": self.api_token})
        if response.get("error"):
            await self._teardown()
            raise BrokerAuthenticationError(
                "Deriv authorization failed", reason=response["error"].get("message", "unknown")
            )

        authorize = response.get("authorize", {})
        self._account_id = authorize.get("loginid")
        self._currency = authorize.get("currency")
        self._connected = True
        logger.info("DerivGateway connected and authorized (account={})", self._account_id)

    async def disconnect(self) -> None:
        await self._teardown()
        logger.info("DerivGateway disconnected")

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def get_account_info(self) -> AccountInfo:
        self._require_connected()
        response = await self._request({"balance": 1})
        if response.get("error"):
            raise BrokerConnectionError(
                "Failed to retrieve Deriv balance", reason=response["error"].get("message")
            )
        balance = response.get("balance", {})
        return AccountInfo(
            account_id=str(balance.get("loginid", self._account_id or "unknown")),
            balance=float(balance.get("balance", 0.0)),
            currency=str(balance.get("currency", self._currency or "USD")),
            equity=float(balance.get("balance", 0.0)),
        )

    async def get_candles(self, symbol: str, timeframe: Timeframe, count: int) -> list[Candle]:
        self._require_connected()
        response = await self._request(
            {
                "ticks_history": symbol,
                "style": "candles",
                "granularity": TIMEFRAME_SECONDS[timeframe],
                "count": count,
                "end": "latest",
            }
        )
        if response.get("error"):
            raise MarketDataError(
                "Failed to retrieve Deriv candle history",
                symbol=symbol,
                reason=response["error"].get("message"),
            )
        return [
            Candle(
                time=datetime.fromtimestamp(candle["epoch"], tz=timezone.utc),
                open=float(candle["open"]),
                high=float(candle["high"]),
                low=float(candle["low"]),
                close=float(candle["close"]),
            )
            for candle in response.get("candles", [])
        ]

    def stream_ticks(self, symbol: str) -> AsyncIterator[Tick]:
        self._require_connected()
        return self._tick_stream(symbol)

    async def submit_order(self, order: OrderRequest) -> OrderResult:
        self._require_connected()
        contract_type = "MULTUP" if order.side is OrderSide.BUY else "MULTDOWN"
        proposal_request: dict[str, Any] = {
            "proposal": 1,
            "contract_type": contract_type,
            "symbol": order.symbol,
            "amount": order.volume,
            "basis": "stake",
            "currency": self._currency or "USD",
            "multiplier": _MULTIPLIER,
        }
        limit_order = {
            key: value
            for key, value in (("stop_loss", order.stop_loss), ("take_profit", order.take_profit))
            if value is not None
        }
        if limit_order:
            proposal_request["limit_order"] = limit_order

        proposal_response = await self._request(proposal_request)
        if proposal_response.get("error"):
            raise ExecutionError(
                "Deriv proposal request failed",
                symbol=order.symbol,
                reason=proposal_response["error"].get("message"),
            )
        proposal = proposal_response.get("proposal", {})

        buy_response = await self._request(
            {"buy": proposal.get("id"), "price": proposal.get("ask_price", order.volume)}
        )
        if buy_response.get("error"):
            logger.warning(
                "DerivGateway order rejected: {} {} {} — {}",
                order.side,
                order.volume,
                order.symbol,
                buy_response["error"].get("message"),
            )
            return OrderResult(
                order_id="",
                status=OrderStatus.REJECTED,
                symbol=order.symbol,
                side=order.side,
                volume=order.volume,
                raw=buy_response,
            )

        buy = buy_response.get("buy", {})
        logger.info(
            "DerivGateway order filled: {} {} {} contract_id={}",
            order.side,
            order.volume,
            order.symbol,
            buy.get("contract_id"),
        )
        return OrderResult(
            order_id=str(buy.get("contract_id", "")),
            status=OrderStatus.FILLED,
            symbol=order.symbol,
            side=order.side,
            volume=order.volume,
            filled_price=float(buy.get("buy_price", 0.0)),
            raw=buy,
        )

    async def get_positions(self) -> list[Position]:
        self._require_connected()
        response = await self._request({"portfolio": 1})
        if response.get("error"):
            raise BrokerConnectionError(
                "Failed to retrieve Deriv portfolio", reason=response["error"].get("message")
            )
        contracts = response.get("portfolio", {}).get("contracts", [])
        return [
            Position(
                position_id=str(contract.get("contract_id", "")),
                symbol=str(contract.get("symbol", "")),
                side=(
                    OrderSide.BUY
                    if "UP" in str(contract.get("contract_type", ""))
                    else OrderSide.SELL
                ),
                volume=float(contract.get("payout", 0.0)),
                open_price=float(contract.get("buy_price", 0.0)),
                opened_at=(
                    datetime.fromtimestamp(contract["date_start"], tz=timezone.utc)
                    if contract.get("date_start")
                    else None
                ),
            )
            for contract in contracts
        ]

    async def get_trade_history(self, count: int = 100) -> list[TradeHistoryEntry]:
        self._require_connected()
        response = await self._request({"profit_table": 1, "limit": count})
        if response.get("error"):
            raise BrokerConnectionError(
                "Failed to retrieve Deriv trade history", reason=response["error"].get("message")
            )
        entries: list[TradeHistoryEntry] = []
        for txn in response.get("profit_table", {}).get("transactions", []):
            buy_price = float(txn.get("buy_price", 0.0))
            sell_price = float(txn.get("sell_price", 0.0))
            entries.append(
                TradeHistoryEntry(
                    trade_id=str(txn.get("contract_id") or txn.get("transaction_id") or ""),
                    symbol=str(txn.get("symbol") or txn.get("shortcode", "")),
                    # NOTE: Deriv's profit_table doesn't directly report
                    # BUY/SELL — approximated from price movement. See
                    # module docstring.
                    side=OrderSide.BUY if sell_price >= buy_price else OrderSide.SELL,
                    volume=buy_price,
                    open_price=buy_price,
                    close_price=sell_price,
                    profit=float(txn.get("profit", sell_price - buy_price)),
                    opened_at=(
                        datetime.fromtimestamp(txn["purchase_time"], tz=timezone.utc)
                        if txn.get("purchase_time")
                        else datetime.now(timezone.utc)
                    ),
                    closed_at=(
                        datetime.fromtimestamp(txn["sell_time"], tz=timezone.utc)
                        if txn.get("sell_time")
                        else datetime.now(timezone.utc)
                    ),
                )
            )
        return entries

    async def _tick_stream(self, symbol: str) -> AsyncIterator[Tick]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._tick_queues[symbol] = queue
        try:
            subscribe_response = await self._request({"ticks": symbol, "subscribe": 1})
        except Exception:
            self._tick_queues.pop(symbol, None)
            raise
        if subscribe_response.get("error"):
            self._tick_queues.pop(symbol, None)
            raise MarketDataError(
                "Failed to subscribe to Deriv ticks",
                symbol=symbol,
                reason=subscribe_response["error"].get("message"),
            )

        subscription_id = subscribe_response.get("subscription", {}).get("id")
        try:
            initial_tick = subscribe_response.get("tick")
            if initial_tick:
                yield self._parse_tick(initial_tick)
            while self._connected:
                message = await queue.get()
                tick = message.get("tick")
                if tick:
                    yield self._parse_tick(tick)
        finally:
            self._tick_queues.pop(symbol, None)
            if subscription_id and self._connected:
                await self._request({"forget": subscription_id})

    async def _read_loop(self) -> None:
        """Background task: demultiplexes incoming messages to pending
        requests (by ``req_id``) or live tick subscriptions (by symbol)."""
        assert self._connection is not None
        try:
            async for raw_message in self._connection:
                message = json.loads(raw_message)
                req_id = message.get("req_id")
                if req_id is not None and req_id in self._pending:
                    future = self._pending.pop(req_id)
                    if not future.done():
                        future.set_result(message)
                    continue
                if message.get("msg_type") == "tick":
                    symbol = message.get("tick", {}).get("symbol")
                    queue = self._tick_queues.get(symbol)
                    if queue is not None:
                        await queue.put(message)
        except websockets.exceptions.ConnectionClosed:
            logger.warning("DerivGateway connection closed unexpectedly")
        finally:
            self._connected = False

    async def _request(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self._connection is None:
            raise BrokerConnectionError("DerivGateway is not connected")
        req_id = next(self._request_ids)
        message = {**payload, "req_id": req_id}
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[req_id] = future
        await self._connection.send(json.dumps(message))
        try:
            return await asyncio.wait_for(future, timeout=self._request_timeout)
        except TimeoutError as exc:
            self._pending.pop(req_id, None)
            raise BrokerConnectionError(
                "Deriv API request timed out", request_type=next(iter(payload))
            ) from exc

    @staticmethod
    def _parse_tick(tick: dict[str, Any]) -> Tick:
        price = float(tick.get("quote", 0.0))
        return Tick(
            time=datetime.fromtimestamp(tick["epoch"], tz=timezone.utc),
            symbol=str(tick.get("symbol", "")),
            bid=float(tick.get("bid", price)),
            ask=float(tick.get("ask", price)),
            last=price,
        )

    async def _teardown(self) -> None:
        self._connected = False
        if self._reader_task is not None:
            self._reader_task.cancel()
            self._reader_task = None
        if self._connection is not None:
            await self._connection.close()
            self._connection = None
        for future in self._pending.values():
            if not future.done():
                future.cancel()
        self._pending.clear()
        self._tick_queues.clear()

    def _require_connected(self) -> None:
        if not self._connected:
            raise BrokerConnectionError("DerivGateway is not connected — call connect() first")
