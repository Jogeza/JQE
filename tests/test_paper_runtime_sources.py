"""Read-only observation-source guarantees for the continuous paper runtime."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from broker.types import AccountInfo, Candle
from core.exceptions import BrokerConnectionError, MarketDataError
from tools import paper_runtime as tool


DEMO_LOGIN = 43274180
STEP = 300


def aligned_candles(count: int = 5, *, lag_steps: int = 1) -> list[Candle]:
    now = datetime.now(timezone.utc)
    anchor = datetime.fromtimestamp(int(now.timestamp()) // STEP * STEP, tz=timezone.utc)
    candles = []
    for index in range(count, 0, -1):
        opened = anchor - timedelta(seconds=STEP * (index + lag_steps - 1))
        candles.append(Candle(
            time=opened, open=100.0, high=101.0, low=99.0, close=100.5,
            volume=10.0, source="mt5",
        ))
    return candles


class FakeGateway:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class FakeTelemetry:
    def __init__(self, gateway: FakeGateway) -> None:
        self.gateway = gateway
        self.connect = AsyncMock()
        self.disconnect = AsyncMock()
        self.get_account_info = AsyncMock(return_value=AccountInfo(
            account_id=str(DEMO_LOGIN), balance=1000.0, currency="USD",
            equity=1000.0, leverage=100.0, server="Weltrade-Demo", trade_mode="demo",
        ))
        self.get_candles = AsyncMock(return_value=aligned_candles())


@pytest.fixture
def weltrade_settings(monkeypatch):
    monkeypatch.setattr(tool.settings, "weltrade_terminal_path", Path("C:/terminal64.exe"))
    monkeypatch.setattr(tool.settings, "weltrade_demo_login", DEMO_LOGIN)
    monkeypatch.setattr(tool.settings, "default_symbol", "FX Vol 20")
    monkeypatch.setattr(tool.settings, "default_timeframe", "M5")
    monkeypatch.setattr(tool, "MT5DemoGateway", FakeGateway)
    monkeypatch.setattr(tool, "VerifiedDemoMT5Telemetry", FakeTelemetry)
    return tool.settings


@pytest.mark.asyncio
async def test_weltrade_source_attaches_without_credentials(weltrade_settings):
    source = tool.WeltradeDemoObservationSource()
    observations = await source()
    gateway = source.telemetry.gateway
    assert gateway.kwargs["login"] is None
    assert gateway.kwargs["password"] is None
    assert gateway.kwargs["server"] is None
    assert gateway.kwargs["expected_environment"] == "demo"
    assert observations and all(item.source == "weltrade_demo" for item in observations)
    assert observations[-1].closed_at <= datetime.now(timezone.utc)


@pytest.mark.asyncio
async def test_weltrade_source_identity_mismatch_fails_closed(weltrade_settings):
    source = tool.WeltradeDemoObservationSource()
    source.telemetry.get_account_info = AsyncMock(return_value=AccountInfo(
        account_id="999", balance=1000.0, currency="USD", trade_mode="demo",
    ))
    with pytest.raises(BrokerConnectionError, match="does not match"):
        await source()
    source.telemetry.disconnect.assert_awaited()
    assert source.connected is False


@pytest.mark.asyncio
async def test_weltrade_source_rejects_stale_candles(weltrade_settings):
    source = tool.WeltradeDemoObservationSource()
    source.telemetry.get_candles = AsyncMock(return_value=aligned_candles(lag_steps=20))
    with pytest.raises(MarketDataError, match="stale"):
        await source()


@pytest.mark.asyncio
async def test_weltrade_source_reconnects_after_connection_loss(weltrade_settings):
    source = tool.WeltradeDemoObservationSource()
    telemetry = source.telemetry
    telemetry.get_candles = AsyncMock(side_effect=[BrokerConnectionError("detached"), aligned_candles()])
    with pytest.raises(BrokerConnectionError):
        await source()
    assert source.connected is False
    observations = await source()
    assert telemetry.connect.await_count == 2
    assert observations and source.connected is True


def test_source_selection_keeps_synthetic_and_rejects_unknown(weltrade_settings, monkeypatch):
    monkeypatch.setattr(tool.settings, "market_data_source", "simulation")
    assert isinstance(tool.build_observation_source(None), tool.SimulationObservationSource)
    assert isinstance(tool.build_observation_source("simulation"), tool.SimulationObservationSource)
    assert isinstance(tool.build_observation_source("broker"), tool.WeltradeDemoObservationSource)
    with pytest.raises(ValueError, match="unsupported"):
        tool.build_observation_source("carrier-pigeon")


def test_weltrade_source_requires_configured_identity(monkeypatch):
    monkeypatch.setattr(tool.settings, "weltrade_terminal_path", None)
    with pytest.raises(MarketDataError, match="terminal path"):
        tool.WeltradeDemoObservationSource()
