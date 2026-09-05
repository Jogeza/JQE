from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest

from broker.deriv_public_data import DerivPublicMarketData
from broker.types import Timeframe
from core.exceptions import BrokerConnectionError, MarketDataError


class FakePublicConnection:
    def __init__(self) -> None:
        self.sent: list[dict] = []
        self._responses: asyncio.Queue[str] = asyncio.Queue()
        self.closed = False

    async def send(self, raw: str) -> None:
        message = json.loads(raw)
        self.sent.append(message)

        if "ticks_history" in message:
            response = {
                "req_id": message["req_id"],
                "candles": [
                    {
                        "epoch": 1_700_000_000,
                        "open": 1900.0,
                        "high": 1902.0,
                        "low": 1899.0,
                        "close": 1901.0,
                    },
                    {
                        "epoch": 1_700_000_900,
                        "open": 1901.0,
                        "high": 1904.0,
                        "low": 1900.0,
                        "close": 1903.0,
                    },
                ],
            }
        elif "active_symbols" in message:
            response = {"req_id": message["req_id"], "active_symbols": [{
                "underlying_symbol": "frxEURUSD", "underlying_symbol_name": "EUR/USD",
                "underlying_symbol_type": "forex", "market": "forex", "subgroup": "none",
                "submarket": "major_pairs", "pip_size": .00001, "trade_count": 1,
                "exchange_is_open": 1, "is_trading_suspended": 0}]}
        else:
            response = {
                "req_id": message["req_id"],
                "error": {"message": "unexpected request"},
            }

        await self._responses.put(json.dumps(response))

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.closed and self._responses.empty():
            raise StopAsyncIteration
        return await self._responses.get()

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_public_connect_does_not_authorize() -> None:
    connection = FakePublicConnection()
    gateway = DerivPublicMarketData(app_id="1089")

    with patch(
        "broker.deriv_public_data.websockets.connect",
        new=AsyncMock(return_value=connection),
    ) as connect:
        await gateway.connect()

    assert gateway.is_connected is True
    assert connection.sent == []

    connect.assert_awaited_once_with(
        "wss://api.derivws.com/trading/v1/options/ws/public"
    )

    await gateway.disconnect()
    assert gateway.is_connected is False


@pytest.mark.asyncio
async def test_public_candles_use_only_ticks_history() -> None:
    connection = FakePublicConnection()
    gateway = DerivPublicMarketData(app_id="1089")

    with patch(
        "broker.deriv_public_data.websockets.connect",
        new=AsyncMock(return_value=connection),
    ):
        await gateway.connect()

    candles = await gateway.get_candles(
        "frxXAUUSD",
        Timeframe.M15,
        2,
    )

    assert len(candles) == 2
    assert candles[0].close == 1901.0
    assert candles[1].close == 1903.0
    assert candles[0].volume is None
    assert candles[0].source == "deriv"

    assert len(connection.sent) == 1
    request = connection.sent[0]

    assert request["ticks_history"] == "frxXAUUSD"
    assert request["style"] == "candles"
    assert request["granularity"] == 900
    assert request["count"] == 2
    assert request["end"] == "latest"

    forbidden = {
        "authorize",
        "proposal",
        "buy",
        "sell",
        "balance",
        "portfolio",
        "profit_table",
    }

    assert forbidden.isdisjoint(request.keys())

    await gateway.disconnect()


def test_public_adapter_has_no_account_or_execution_api() -> None:
    gateway = DerivPublicMarketData(app_id="1089")

    assert not hasattr(gateway, "api_token")
    assert not hasattr(gateway, "get_account_info")
    assert not hasattr(gateway, "submit_order")
    assert not hasattr(gateway, "get_positions")
    assert not hasattr(gateway, "get_trade_history")


@pytest.mark.asyncio
async def test_public_active_symbols_uses_exact_unauthenticated_request() -> None:
    connection = FakePublicConnection(); source = DerivPublicMarketData()
    with patch("broker.deriv_public_data.websockets.connect", new=AsyncMock(return_value=connection)):
        await source.connect()
    payload = await source.get_active_symbols()
    assert payload["active_symbols"][0]["underlying_symbol"] == "frxEURUSD"
    assert connection.sent[0]["active_symbols"] == "full"
    assert set(connection.sent[0]) == {"active_symbols", "req_id"}
    await source.disconnect()


@pytest.mark.asyncio
async def test_public_candles_fail_when_disconnected() -> None:
    gateway = DerivPublicMarketData(app_id="1089")

    with pytest.raises(BrokerConnectionError):
        await gateway.get_candles("frxXAUUSD", Timeframe.M15, 2)


@pytest.mark.asyncio
async def test_public_candle_count_must_be_positive() -> None:
    connection = FakePublicConnection()
    gateway = DerivPublicMarketData(app_id="1089")

    with patch(
        "broker.deriv_public_data.websockets.connect",
        new=AsyncMock(return_value=connection),
    ):
        await gateway.connect()

    with pytest.raises(MarketDataError):
        await gateway.get_candles("frxXAUUSD", Timeframe.M15, 0)

    assert connection.sent == []

    await gateway.disconnect()

def test_public_adapter_satisfies_candle_data_source_protocol() -> None:
    from data.historical import CandleDataSource

    gateway = DerivPublicMarketData(app_id="1089")

    assert isinstance(gateway, CandleDataSource)


def test_public_adapter_can_be_injected_into_historical_service(tmp_path) -> None:
    from data.historical import HistoricalDataService
    from data.storage import CandleStore

    gateway = DerivPublicMarketData(app_id="1089")
    store = CandleStore(tmp_path / "candles.sqlite3")

    service = HistoricalDataService(gateway, store=store)

    assert service.gateway is gateway

def test_public_adapter_satisfies_candle_data_source_protocol() -> None:
    from data.historical import CandleDataSource

    gateway = DerivPublicMarketData(app_id="1089")

    assert isinstance(gateway, CandleDataSource)


def test_public_adapter_can_be_injected_into_historical_service(tmp_path) -> None:
    from data.historical import HistoricalDataService
    from data.storage import CandleStore

    gateway = DerivPublicMarketData(app_id="1089")
    store = CandleStore(tmp_path / "candles.sqlite3")

    service = HistoricalDataService(gateway, store=store)

    assert service.gateway is gateway

@pytest.mark.asyncio
async def test_public_adapter_historical_service_persists_candles(tmp_path) -> None:
    from data.historical import HistoricalDataService
    from data.storage import CandleStore

    connection = FakePublicConnection()
    gateway = DerivPublicMarketData(app_id="1089")
    store = CandleStore(tmp_path / "candles.sqlite3")
    service = HistoricalDataService(gateway, store=store)

    with patch(
        "broker.deriv_public_data.websockets.connect",
        new=AsyncMock(return_value=connection),
    ):
        await gateway.connect()

    result = await service.get_candles(
        "frxXAUUSD",
        Timeframe.M15,
        2,
        fill_gaps=False,
    )

    assert len(result) == 2
    assert store.count("frxXAUUSD", Timeframe.M15) == 2

    cached = store.load_candles(
        "frxXAUUSD",
        Timeframe.M15,
    )

    assert len(cached) == 2
    assert cached[0].time < cached[1].time
    assert cached[0].source == "deriv"
    assert cached[0].volume is None

    request = connection.sent[0]
    assert request["ticks_history"] == "frxXAUUSD"
    assert request["granularity"] == 900

    forbidden = {
        "authorize",
        "proposal",
        "buy",
        "sell",
        "balance",
        "portfolio",
        "profit_table",
    }
    assert forbidden.isdisjoint(request.keys())

    await gateway.disconnect()
