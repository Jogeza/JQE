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

    In particular, :meth:`submit_order` remains fail-closed until registered
    evidence supplies an authoritative multiplier and monetary limit amounts.
    Broker-neutral absolute stop/take-profit prices are never serialized as
    Deriv ``limit_order`` loss/profit amounts.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import math
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


def _positive_financial_number(value: Any, *, field: str) -> float:
    """Normalize a positive finite commercial value without zero fallbacks."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ExecutionError(f"Deriv proposal {field} was malformed or indeterminate")
    if isinstance(value, str) and not value.strip():
        raise ExecutionError(f"Deriv proposal {field} was malformed or indeterminate")
    try:
        normalized = float(value)
    except (TypeError, ValueError) as exc:
        raise ExecutionError(
            f"Deriv proposal {field} was malformed or indeterminate"
        ) from exc
    if not math.isfinite(normalized) or normalized <= 0:
        raise ExecutionError(f"Deriv proposal {field} was malformed or indeterminate")
    return normalized


def _build_proposal_request(order: OrderRequest, currency: str) -> dict[str, Any]:
    """Build only the verified base proposal schema; add no unproven terms."""
    if order.stop_loss is not None or order.take_profit is not None:
        raise ExecutionError(
            "Deriv monetary limit conversion is unproven; absolute market "
            "stop-loss/take-profit prices cannot be used as contract loss/profit amounts",
            symbol=order.symbol,
        )
    return {
        "proposal": 1,
        "contract_type": "MULTUP" if order.side is OrderSide.BUY else "MULTDOWN",
        "underlying_symbol": order.symbol,
        "amount": order.quantity.value,
        "basis": "stake",
        "currency": currency,
    }


def _parse_proposal_response(response: dict[str, Any], *, symbol: str) -> tuple[str, float]:
    proposal = response.get("proposal")
    if not isinstance(proposal, dict):
        raise ExecutionError(
            "Deriv proposal response was malformed or indeterminate", symbol=symbol
        )
    proposal_id = proposal.get("id")
    if not isinstance(proposal_id, str) or not proposal_id.strip():
        raise ExecutionError(
            "Deriv proposal response was malformed or indeterminate", symbol=symbol
        )
    try:
        ask_price = _positive_financial_number(proposal.get("ask_price"), field="ask_price")
    except ExecutionError as exc:
        raise ExecutionError(
            "Deriv proposal response was malformed or indeterminate", symbol=symbol
        ) from exc
    return proposal_id, ask_price


def _build_buy_request(
    proposal_id: str, ask_price: float, idempotency_key: str | None
) -> dict[str, Any]:
    request: dict[str, Any] = {"buy": proposal_id, "price": ask_price}
    if idempotency_key is not None:
        request["passthrough"] = {"jqe": {"idempotency_key": idempotency_key}}
    return request


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
        expected_environment: str | None = None,
    ) -> None:
        if not api_token:
            raise BrokerAuthenticationError("Deriv API token is required")
        self.api_token = api_token
        self.app_id = app_id
        self.endpoint = endpoint
        self._request_timeout = request_timeout
        self.expected_environment = expected_environment

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
        if not isinstance(authorize, dict):
            await self._teardown()
            raise BrokerAuthenticationError("Deriv authorization identity was malformed")
        if self.expected_environment != "demo":
            await self._teardown()
            raise BrokerAuthenticationError("Deriv environment is missing or is not DEMO")
        # `is_virtual` is broker-supplied authorization evidence.  Configuration
        # alone is never accepted as proof that the account is a demo account.
        if authorize.get("is_virtual") not in (True, 1):
            await self._teardown()
            raise BrokerAuthenticationError("Deriv account is not authoritatively verified as DEMO")
        account_id = authorize.get("loginid")
        currency = authorize.get("currency")
        if not isinstance(account_id, str) or not account_id.strip():
            await self._teardown()
            raise BrokerAuthenticationError("Deriv account identity is missing")
        if not isinstance(currency, str) or not currency.strip():
            await self._teardown()
            raise BrokerAuthenticationError("Deriv account currency is missing")
        self._account_id = account_id.strip()
        self._currency = currency.strip()
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
        if not isinstance(balance, dict) or balance.get("loginid") != self._account_id:
            raise BrokerConnectionError("Deriv balance account identity mismatch")
        return AccountInfo(
            account_id=self._account_id,
            balance=float(balance["balance"]),
            currency=str(balance.get("currency", self._currency)),
            equity=float(balance["balance"]),
        )

    async def get_candles(
        self, symbol: str, timeframe: Timeframe, count: int, end: datetime | None = None
    ) -> list[Candle]:
        self._require_connected()
        response = await self._request(
            {
                "ticks_history": symbol,
                "style": "candles",
                "granularity": TIMEFRAME_SECONDS[timeframe],
                "count": count,
                "end": int(end.timestamp()) if end is not None else "latest",
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
                volume=None,
                source="deriv",
            )
            for candle in response.get("candles", [])
        ]

    def stream_ticks(self, symbol: str) -> AsyncIterator[Tick]:
        self._require_connected()
        return self._tick_stream(symbol)

    async def submit_order(self, order: OrderRequest) -> OrderResult:
        self._require_connected()
        from broker.types import ExecutionQuantityUnit
        if order.quantity.unit is not ExecutionQuantityUnit.DERIV_STAKE:
            raise ExecutionError("Deriv requires DERIV_STAKE")
        quantity = order.quantity.value
        proposal_request = _build_proposal_request(order, self._currency or "USD")

        # No registered evidence currently supplies an authoritative multiplier.
        # MULTUP/MULTDOWN execution therefore remains unreachable, and no proposal
        # request is sent.  The base request above is retained as the corrected,
        # offline-testable API schema boundary.
        raise ExecutionError(
            "Deriv multiplier is unverified; proposal submission is disabled",
            symbol=order.symbol,
        )

        proposal_response = await self._request(proposal_request)
        if proposal_response.get("error"):
            raise ExecutionError(
                "Deriv proposal request failed",
                symbol=order.symbol,
                reason=proposal_response["error"].get("message"),
            )
        proposal_id, ask_price = _parse_proposal_response(
            proposal_response, symbol=order.symbol
        )
        buy_request = _build_buy_request(
            proposal_id, ask_price, order.idempotency_key
        )
        buy_response = await self._request(buy_request)
        if buy_response.get("error"):
            logger.warning(
                "DerivGateway order rejected: {} {} {} — {}",
                order.side,
                quantity,
                order.symbol,
                buy_response["error"].get("message"),
            )
            return OrderResult(
                order_id="",
                status=OrderStatus.REJECTED,
                symbol=order.symbol,
                side=order.side,
                volume=quantity,
                raw=buy_response,
            )

        buy = buy_response.get("buy")
        contract_id = buy.get("contract_id") if isinstance(buy, dict) else None
        buy_price = buy.get("buy_price") if isinstance(buy, dict) else None
        if (
            contract_id in (None, "")
            or not isinstance(buy_price, (int, float))
            or isinstance(buy_price, bool)
            or not math.isfinite(float(buy_price))
            or float(buy_price) <= 0
        ):
            raise ExecutionError("Deriv buy response was malformed or outcome is indeterminate", symbol=order.symbol)
        logger.info(
            "DerivGateway order filled: {} {} {} contract_id={}",
            order.side,
            quantity,
            order.symbol,
            contract_id,
        )
        return OrderResult(
            order_id=str(contract_id),
            status=OrderStatus.FILLED,
            symbol=order.symbol,
            side=order.side,
            volume=quantity,
            filled_price=float(buy_price),
            transaction_id=(str(buy["transaction_id"]) if buy.get("transaction_id") is not None else None),
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
                transaction_id=(str(contract["transaction_id"]) if contract.get("transaction_id") is not None else None),
                contract_type=str(contract.get("contract_type")) if contract.get("contract_type") is not None else None,
            )
            for contract in contracts
        ]

    async def get_trade_history(self, count: int = 100) -> list[TradeHistoryEntry]:
        self._require_connected()
        # NOTE: The Deriv profit_table API is documented at
        # https://developers.deriv.com/docs/profit_table. The API
        # supports a "limit" parameter but does NOT document a
        # date_from/date_to filter as of this implementation.
        # We intentionally do NOT add an unverified parameter.
        # Reconciliation uses closed_at (derived from sell_time) to
        # filter records to today — records with missing or invalid
        # sell_time are excluded rather than silently assigned a
        # synthetic timestamp (see guard below).
        response = await self._request({"profit_table": 1, "limit": count, "sort": "DESC"})
        if response.get("error"):
            raise BrokerConnectionError(
                "Failed to retrieve Deriv trade history", reason=response["error"].get("message")
            )
        entries: list[TradeHistoryEntry] = []
        for txn in response.get("profit_table", {}).get("transactions", []):
            buy_price = float(txn.get("buy_price", 0.0))
            sell_price = float(txn.get("sell_price", 0.0))

            # contract_id is the canonical Deriv identifier for a closed
            # contract. It is stable across API calls and must exist for
            # every entry in profit_table. If it is absent the record is
            # malformed and we skip it with a warning.
            raw_contract_id = txn.get("contract_id")
            if not raw_contract_id:
                logger.warning(
                    "DerivGateway: profit_table entry missing contract_id — skipping: {}",
                    txn,
                )
                continue

            # sell_time is the Unix epoch of the contract's close. If it
            # is absent we MUST NOT fall back to datetime.now() — that
            # would assign today's date to an unknown historical record
            # and corrupt daily risk reconciliation. Skip instead.
            raw_sell_time = txn.get("sell_time")
            if not raw_sell_time:
                logger.warning(
                    "DerivGateway: profit_table entry for contract_id={} has no"
                    " sell_time — skipping to avoid assigning a synthetic close"
                    " timestamp",
                    raw_contract_id,
                )
                continue

            # purchase_time should always accompany sell_time. If it is
            # absent we use sell_time as a safe approximation (it does
            # not affect reconciliation, which only uses closed_at).
            raw_purchase_time = txn.get("purchase_time") or raw_sell_time

            entries.append(
                TradeHistoryEntry(
                    trade_id=str(raw_contract_id),
                    symbol=str(txn.get("symbol") or txn.get("shortcode", "")),
                    # NOTE: Deriv's profit_table doesn't directly report
                    # BUY/SELL — approximated from price movement. See
                    # module docstring.
                    side=OrderSide.BUY if sell_price >= buy_price else OrderSide.SELL,
                    volume=buy_price,
                    open_price=buy_price,
                    close_price=sell_price,
                    profit=float(txn.get("profit", sell_price - buy_price)),
                    opened_at=datetime.fromtimestamp(raw_purchase_time, tz=timezone.utc),
                    closed_at=datetime.fromtimestamp(raw_sell_time, tz=timezone.utc),
                    transaction_id=(str(txn["transaction_id"]) if txn.get("transaction_id") is not None else None),
                    contract_type=str(txn.get("contract_type")) if txn.get("contract_type") is not None else None,
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
        except websockets.exceptions.ConnectionClosed as exc:
            logger.warning("DerivGateway connection closed unexpectedly")
            self._fail_pending("Deriv WebSocket connection closed", exc)
        except Exception as exc:
            logger.warning("DerivGateway reader failed; pending requests were aborted")
            self._fail_pending("Deriv WebSocket reader failed", exc)
        finally:
            self._connected = False
            if self._pending:
                self._fail_pending(
                    "Deriv WebSocket reader ended before responses arrived",
                    RuntimeError("reader ended"),
                )

    async def _request(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self._connection is None:
            raise BrokerConnectionError("DerivGateway is not connected")
        req_id = next(self._request_ids)
        message = {**payload, "req_id": req_id}
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[req_id] = future
        try:
            await self._connection.send(json.dumps(message))
        except Exception as exc:
            self._pending.pop(req_id, None)
            if not future.done():
                future.cancel()
            raise BrokerConnectionError(
                "Deriv API request could not be sent", request_type=next(iter(payload))
            ) from exc
        try:
            return await asyncio.wait_for(future, timeout=self._request_timeout)
        except TimeoutError as exc:
            self._pending.pop(req_id, None)
            raise BrokerConnectionError(
                "Deriv API request timed out", request_type=next(iter(payload))
            ) from exc

    def _fail_pending(self, message: str, cause: Exception) -> None:
        for req_id, future in tuple(self._pending.items()):
            self._pending.pop(req_id, None)
            if not future.done():
                future.set_exception(BrokerConnectionError(message, reason=type(cause).__name__))

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
