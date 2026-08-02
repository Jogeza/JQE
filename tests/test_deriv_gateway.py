"""Tests for broker.deriv_gateway.DerivGateway.

The real Deriv API is a live WebSocket service this sandbox cannot
reach — see the module docstring in broker/deriv_gateway.py. These
tests exercise DerivGateway's own logic (request/response correlation,
error mapping, DTO construction) against a scripted fake connection,
not a real server.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from broker.deriv_gateway import DerivGateway
from broker.types import OrderRequest, OrderSide, OrderStatus, Timeframe
from core.exceptions import (
    BrokerAuthenticationError,
    BrokerConnectionError,
    MarketDataError,
)


class FakeDerivConnection:
    """A scripted stand-in for a websockets connection to Deriv.

    Queues one canned response per outgoing request, keyed by request
    type (the first non-``req_id`` key in the payload), and replays it
    back to the gateway's read loop with the matching ``req_id``
    attached — mirroring how the read loop correlates real responses.
    """

    def __init__(self, responses: dict[str, dict[str, Any]]) -> None:
        self._responses = responses
        self._incoming: asyncio.Queue[str] = asyncio.Queue()
        self.sent: list[dict[str, Any]] = []
        self.closed = False

    async def send(self, raw_message: str) -> None:
        message = json.loads(raw_message)
        self.sent.append(message)
        request_type = next(key for key in message if key != "req_id")
        response = dict(
            self._responses.get(request_type, {"error": {"message": "unscripted request"}})
        )
        response["req_id"] = message["req_id"]
        await self._incoming.put(json.dumps(response))

    async def close(self) -> None:
        self.closed = True
        await self._incoming.put(None)  # unblocks __anext__ with StopAsyncIteration

    def __aiter__(self) -> AsyncIterator[str]:
        return self

    async def __anext__(self) -> str:
        item = await self._incoming.get()
        if item is None:
            raise StopAsyncIteration
        return item


def _connected_gateway(
    responses: dict[str, dict[str, Any]],
) -> tuple[DerivGateway, FakeDerivConnection]:
    fake_connection = FakeDerivConnection(
        {"authorize": {"authorize": {"loginid": "CR12345", "currency": "USD"}}, **responses}
    )
    gateway = DerivGateway(api_token="test-token", app_id="1089")
    return gateway, fake_connection


async def _connect_with_fake(gateway: DerivGateway, fake_connection: FakeDerivConnection) -> None:
    with patch(
        "broker.deriv_gateway.websockets.connect", new=AsyncMock(return_value=fake_connection)
    ):
        await gateway.connect()


class TestConstruction:
    def test_empty_token_rejected(self) -> None:
        with pytest.raises(BrokerAuthenticationError):
            DerivGateway(api_token="", app_id="1089")


class TestConnect:
    async def test_successful_authorize_marks_connected(self) -> None:
        gateway, fake_connection = _connected_gateway({})
        await _connect_with_fake(gateway, fake_connection)
        assert gateway.is_connected is True
        await gateway.disconnect()

    async def test_failed_authorize_raises_and_stays_disconnected(self) -> None:
        gateway, fake_connection = _connected_gateway(
            {"authorize": {"error": {"message": "InvalidToken"}}}
        )
        with pytest.raises(BrokerAuthenticationError):
            await _connect_with_fake(gateway, fake_connection)
        assert gateway.is_connected is False


class TestGetAccountInfo:
    async def test_maps_balance_response(self) -> None:
        gateway, fake_connection = _connected_gateway(
            {"balance": {"balance": {"balance": 1234.5, "currency": "USD", "loginid": "CR12345"}}}
        )
        await _connect_with_fake(gateway, fake_connection)
        account = await gateway.get_account_info()
        assert account.balance == 1234.5
        assert account.currency == "USD"
        await gateway.disconnect()

    async def test_raises_on_error_response(self) -> None:
        gateway, fake_connection = _connected_gateway({"balance": {"error": {"message": "boom"}}})
        await _connect_with_fake(gateway, fake_connection)
        with pytest.raises(BrokerConnectionError):
            await gateway.get_account_info()
        await gateway.disconnect()

    async def test_raises_when_not_connected(self) -> None:
        gateway = DerivGateway(api_token="test-token", app_id="1089")
        with pytest.raises(BrokerConnectionError):
            await gateway.get_account_info()


class TestGetCandles:
    async def test_maps_candle_response(self) -> None:
        gateway, fake_connection = _connected_gateway(
            {
                "ticks_history": {
                    "candles": [
                        {"epoch": 1700000000, "open": 1.0, "high": 1.2, "low": 0.9, "close": 1.1},
                        {"epoch": 1700000300, "open": 1.1, "high": 1.3, "low": 1.0, "close": 1.2},
                    ]
                }
            }
        )
        await _connect_with_fake(gateway, fake_connection)
        candles = await gateway.get_candles("R_100", Timeframe.M5, 2)
        assert len(candles) == 2
        assert candles[0].close == 1.1
        await gateway.disconnect()

    async def test_raises_market_data_error_on_error_response(self) -> None:
        gateway, fake_connection = _connected_gateway(
            {"ticks_history": {"error": {"message": "InvalidSymbol"}}}
        )
        await _connect_with_fake(gateway, fake_connection)
        with pytest.raises(MarketDataError):
            await gateway.get_candles("NOT_A_SYMBOL", Timeframe.M5, 10)
        await gateway.disconnect()


class TestSubmitOrder:
    async def test_buy_order_flows_through_proposal_and_buy(self) -> None:
        gateway, fake_connection = _connected_gateway(
            {
                "proposal": {"proposal": {"id": "prop-1", "ask_price": 10.0}},
                "buy": {"buy": {"contract_id": 999, "buy_price": 10.0}},
            }
        )
        await _connect_with_fake(gateway, fake_connection)
        result = await gateway.submit_order(
            OrderRequest(symbol="R_100", side=OrderSide.BUY, volume=10.0)
        )
        assert result.status is OrderStatus.FILLED
        assert result.order_id == "999"
        await gateway.disconnect()

    async def test_rejected_buy_returns_rejected_status(self) -> None:
        gateway, fake_connection = _connected_gateway(
            {
                "proposal": {"proposal": {"id": "prop-1", "ask_price": 10.0}},
                "buy": {"error": {"message": "insufficient balance"}},
            }
        )
        await _connect_with_fake(gateway, fake_connection)
        result = await gateway.submit_order(
            OrderRequest(symbol="R_100", side=OrderSide.BUY, volume=10.0)
        )
        assert result.status is OrderStatus.REJECTED
        await gateway.disconnect()


class TestGetPositions:
    async def test_maps_portfolio_contracts(self) -> None:
        gateway, fake_connection = _connected_gateway(
            {
                "portfolio": {
                    "portfolio": {
                        "contracts": [
                            {
                                "contract_id": 1,
                                "symbol": "R_100",
                                "contract_type": "MULTUP",
                                "payout": 5.0,
                                "buy_price": 10.0,
                                "date_start": 1700000000,
                            }
                        ]
                    }
                }
            }
        )
        await _connect_with_fake(gateway, fake_connection)
        positions = await gateway.get_positions()
        assert len(positions) == 1
        assert positions[0].side is OrderSide.BUY
        await gateway.disconnect()
