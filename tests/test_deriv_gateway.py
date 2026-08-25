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
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from broker.deriv_gateway import DerivGateway
from broker.types import OrderRequest, OrderSide, OrderStatus, Timeframe
from core.exceptions import (
    BrokerAuthenticationError,
    BrokerConnectionError,
    ExecutionError,
    MarketDataError,
)


class FakeDerivConnection:
    """A scripted stand-in for a websockets connection to Deriv.

    Queues one canned response per outgoing request, keyed by request
    type (the first non-``req_id`` key in the payload), and replays it
    back to the gateway's read loop with the matching ``req_id``
    attached — mirroring how the read loop correlates real responses.
    """

    def __init__(
        self, responses: dict[str, dict[str, Any]], ignore_requests: set[str] | None = None
    ) -> None:
        self._responses = responses
        self._ignore_requests = ignore_requests or set()
        self._incoming: asyncio.Queue[str] = asyncio.Queue()
        self.sent: list[dict[str, Any]] = []
        self.closed = False

    async def send(self, raw_message: str) -> None:
        message = json.loads(raw_message)
        self.sent.append(message)
        request_type = next(key for key in message if key != "req_id")
        if request_type in self._ignore_requests:
            return
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

    async def test_omitting_end_requests_latest(self) -> None:
        gateway, fake_connection = _connected_gateway({"ticks_history": {"candles": []}})
        await _connect_with_fake(gateway, fake_connection)
        await gateway.get_candles("R_100", Timeframe.M5, 10)
        request = next(m for m in fake_connection.sent if "ticks_history" in m)
        assert request["end"] == "latest"
        await gateway.disconnect()

    async def test_given_end_is_sent_as_epoch_seconds(self) -> None:
        gateway, fake_connection = _connected_gateway({"ticks_history": {"candles": []}})
        await _connect_with_fake(gateway, fake_connection)
        end = datetime(2024, 6, 1, tzinfo=timezone.utc)
        await gateway.get_candles("R_100", Timeframe.M5, 10, end=end)
        request = next(m for m in fake_connection.sent if "ticks_history" in m)
        assert request["end"] == int(end.timestamp())
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

    async def test_proposal_error_raises_execution_error(self) -> None:
        gateway, fake_connection = _connected_gateway(
            {
                "proposal": {"error": {"message": "ContractNotAvailable"}},
            }
        )
        await _connect_with_fake(gateway, fake_connection)
        with pytest.raises(ExecutionError, match="Deriv proposal request failed"):
            await gateway.submit_order(
                OrderRequest(symbol="R_100", side=OrderSide.BUY, volume=10.0)
            )
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

    async def test_portfolio_error_raises_broker_connection_error(self) -> None:
        gateway, fake_connection = _connected_gateway(
            {
                "portfolio": {"error": {"message": "ServerError"}},
            }
        )
        await _connect_with_fake(gateway, fake_connection)
        with pytest.raises(BrokerConnectionError, match="Failed to retrieve Deriv portfolio"):
            await gateway.get_positions()
        await gateway.disconnect()


class TestRequestTimeout:
    async def test_request_timeout_raises_broker_connection_error(self) -> None:
        fake_connection = FakeDerivConnection(
            {"authorize": {"authorize": {"loginid": "CR12345", "currency": "USD"}}},
            ignore_requests={"balance"},
        )
        gateway = DerivGateway(api_token="test-token", app_id="1089", request_timeout=0.05)
        await _connect_with_fake(gateway, fake_connection)

        with pytest.raises(BrokerConnectionError, match="timed out"):
            await gateway.get_account_info()
        await gateway.disconnect()


# ---------------------------------------------------------------------------
# Helper: build a minimal valid profit_table transaction dict
# ---------------------------------------------------------------------------

def _txn(
    *,
    contract_id: int = 1001,
    symbol: str = "R_100",
    buy_price: float = 10.0,
    sell_price: float = 8.0,
    profit: float = -2.0,
    purchase_time: int | None = 1_700_000_000,
    sell_time: int | None = 1_700_003_600,
) -> dict:
    result: dict = {
        "symbol": symbol,
        "buy_price": buy_price,
        "sell_price": sell_price,
        "profit": profit,
    }
    if contract_id is not None:
        result["contract_id"] = contract_id
    if purchase_time is not None:
        result["purchase_time"] = purchase_time
    if sell_time is not None:
        result["sell_time"] = sell_time
    return result


class TestGetTradeHistory:
    """Tests for DerivGateway.get_trade_history timestamp and ID hardening."""

    async def test_missing_sell_time_record_is_skipped(self) -> None:
        """Test 8: A record with no sell_time must be silently skipped —
        NOT converted to datetime.now() which would corrupt reconciliation."""
        import datetime as _dt

        gateway, fake_connection = _connected_gateway(
            {
                "profit_table": {
                    "profit_table": {
                        "transactions": [_txn(contract_id=1, sell_time=None)]
                    }
                }
            }
        )
        await _connect_with_fake(gateway, fake_connection)
        result = await gateway.get_trade_history()

        # The record must be excluded — not present with today's date.
        assert result == [], (
            "Records with missing sell_time must be excluded, not assigned datetime.now()"
        )
        await gateway.disconnect()

    async def test_missing_contract_id_record_is_skipped(self) -> None:
        """Test 11 (stable ID): A malformed record with no contract_id must
        be skipped, not assigned an empty string trade_id."""
        gateway, fake_connection = _connected_gateway(
            {
                "profit_table": {
                    "profit_table": {
                        "transactions": [_txn(contract_id=None)]
                    }
                }
            }
        )
        await _connect_with_fake(gateway, fake_connection)
        result = await gateway.get_trade_history()

        assert result == [], "Records with missing contract_id must be excluded"
        await gateway.disconnect()

    async def test_valid_sell_time_is_mapped_correctly(self) -> None:
        """Test 9: A valid sell_time epoch is correctly converted to a UTC datetime."""
        import datetime as _dt

        sell_epoch = 1_700_010_000  # a fixed known timestamp
        expected_closed_at = _dt.datetime.fromtimestamp(sell_epoch, tz=_dt.timezone.utc)

        gateway, fake_connection = _connected_gateway(
            {
                "profit_table": {
                    "profit_table": {
                        "transactions": [_txn(contract_id=42, sell_time=sell_epoch)]
                    }
                }
            }
        )
        await _connect_with_fake(gateway, fake_connection)
        result = await gateway.get_trade_history()

        assert len(result) == 1
        assert result[0].closed_at == expected_closed_at, (
            f"closed_at must be {expected_closed_at}, got {result[0].closed_at}"
        )
        await gateway.disconnect()

    async def test_trade_id_is_stable_contract_id(self) -> None:
        """Test 11: trade_id must be str(contract_id) — stable across API calls."""
        gateway, fake_connection = _connected_gateway(
            {
                "profit_table": {
                    "profit_table": {
                        "transactions": [_txn(contract_id=99999)]
                    }
                }
            }
        )
        await _connect_with_fake(gateway, fake_connection)
        result = await gateway.get_trade_history()

        assert len(result) == 1
        assert result[0].trade_id == "99999"
        await gateway.disconnect()

    async def test_records_with_old_sell_time_excluded_by_reconciliation(self) -> None:
        """Test 12: Historical contracts (non-today sell_time) produce entries
        with a past closed_at date that reconciliation correctly excludes.
        The gateway itself returns them — the date filter lives in RiskEngine."""
        import datetime as _dt

        # A sell_time clearly in the past (2023)
        old_epoch = 1_672_531_200   # 2023-01-01 00:00:00 UTC
        today_epoch = int(_dt.datetime.now(_dt.timezone.utc).timestamp())

        gateway, fake_connection = _connected_gateway(
            {
                "profit_table": {
                    "profit_table": {
                        "transactions": [
                            _txn(contract_id=1, sell_time=old_epoch, profit=-5.0),
                            _txn(contract_id=2, sell_time=today_epoch, profit=-10.0),
                        ]
                    }
                }
            }
        )
        await _connect_with_fake(gateway, fake_connection)
        result = await gateway.get_trade_history()

        # Gateway returns both — reconciliation filters later.
        assert len(result) == 2

        # Verify the old one has a past date, not today's date.
        today = _dt.datetime.now(_dt.timezone.utc).date()
        old_entry = next(e for e in result if e.trade_id == "1")
        today_entry = next(e for e in result if e.trade_id == "2")

        assert old_entry.closed_at.date() < today, (
            "Old sell_time must map to a past date, not today's date"
        )
        assert today_entry.closed_at.date() == today

        await gateway.disconnect()

    async def test_profit_table_request_does_not_include_unverified_date_from(
        self,
    ) -> None:
        """Test 10: The profit_table request must NOT include a date_from parameter
        because the Deriv API contract does not document it and adding an
        unverified parameter could cause silent failures or unexpected behavior."""
        gateway, fake_connection = _connected_gateway(
            {"profit_table": {"profit_table": {"transactions": []}}}
        )
        await _connect_with_fake(gateway, fake_connection)
        await gateway.get_trade_history()

        pt_request = next(
            (m for m in fake_connection.sent if "profit_table" in m), None
        )
        assert pt_request is not None, "profit_table request must be sent"
        assert "date_from" not in pt_request, (
            "date_from must NOT be included — it is not verified against "
            "the Deriv API contract and its behavior is undefined"
        )
        await gateway.disconnect()

    async def test_profit_table_request_sends_sort_desc(self) -> None:
        """Test 10 (continued): The request should include sort=DESC to get
        the most recent contracts first, ensuring the count cap covers today."""
        gateway, fake_connection = _connected_gateway(
            {"profit_table": {"profit_table": {"transactions": []}}}
        )
        await _connect_with_fake(gateway, fake_connection)
        await gateway.get_trade_history(count=50)

        pt_request = next(
            (m for m in fake_connection.sent if "profit_table" in m), None
        )
        assert pt_request is not None
        assert pt_request.get("sort") == "DESC", (
            "sort=DESC ensures newest contracts are fetched first so that "
            "today's records are included when count is reached"
        )
        assert pt_request.get("limit") == 50
        await gateway.disconnect()

    async def test_missing_purchase_time_falls_back_to_sell_time(self) -> None:
        """Missing purchase_time should not cause a skip — sell_time is used
        as the opened_at fallback. closed_at must still be the sell_time."""
        import datetime as _dt

        sell_epoch = 1_700_020_000
        expected_dt = _dt.datetime.fromtimestamp(sell_epoch, tz=_dt.timezone.utc)

        txn = _txn(contract_id=77, sell_time=sell_epoch, purchase_time=None)
        gateway, fake_connection = _connected_gateway(
            {"profit_table": {"profit_table": {"transactions": [txn]}}}
        )
        await _connect_with_fake(gateway, fake_connection)
        result = await gateway.get_trade_history()

        assert len(result) == 1, "Missing purchase_time alone must not skip the record"
        assert result[0].closed_at == expected_dt
        assert result[0].opened_at == expected_dt, (
            "opened_at should fall back to sell_time when purchase_time is absent"
        )
        await gateway.disconnect()
