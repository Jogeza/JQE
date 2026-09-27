"""Offline regressions for provider isolation and account-scoped risk telemetry."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from api.service import ApplicationService
from broker.types import Candle, Timeframe
from config.settings import settings
from data.storage import CandleStore
from execution.safety import (
    RiskAuthorizationSnapshot,
    RiskEvaluationState,
    SQLiteExecutionSafetyStore,
)


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "broker", "weltrade")
    monkeypatch.setattr(settings, "market_data_source", "broker")
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "weltrade_demo_login", 4242)
    monkeypatch.setattr(settings, "weltrade_login", None)
    monkeypatch.setattr(settings, "execution_safety_store_path", tmp_path / "safety.sqlite3")
    return ApplicationService(
        gateway=AsyncMock(), candle_store=CandleStore(tmp_path / "candles.sqlite3")
    )


def candles():
    start = datetime.now(timezone.utc).replace(second=0, microsecond=0) - timedelta(minutes=5)
    return [Candle(time=start + timedelta(minutes=i), open=100, high=102,
                   low=99, close=101, volume=10, source="weltrade") for i in range(3)]


async def test_dashboard_refresh_writes_only_weltrade_partition(service):
    bars = candles()
    store = service._candle_store
    for provider in ("broker", "deriv"):
        store.save_candles("FX VOL 20", Timeframe.M1, bars, provider=provider)
    service._gateway.get_candles.return_value = bars

    result, provenance, status, _ = await service._get_market_candle_data("FX VOL 20", Timeframe.M1, 3)

    assert result == bars
    assert (provenance, status) == ("BROKER", "CURRENT")
    assert store.load_latest("FX VOL 20", Timeframe.M1, 3, provider="weltrade") == bars
    for provider in ("broker", "deriv"):
        assert store.load_latest("FX VOL 20", Timeframe.M1, 3, provider=provider) == bars
    service._gateway.get_candles.assert_awaited()
    service._gateway.submit_order.assert_not_awaited()


@pytest.mark.parametrize("provider,expected", [("broker", "UNAVAILABLE"), ("deriv", "UNAVAILABLE"), ("weltrade", "CACHED")])
async def test_dashboard_failure_only_falls_back_to_weltrade(service, provider, expected):
    bars = candles()
    service._candle_store.save_candles("FX VOL 20", Timeframe.M1, bars, provider=provider)
    service._gateway.get_candles.side_effect = RuntimeError("Offline terminal")
    result, _, status, _ = await service._get_market_candle_data("FX VOL 20", Timeframe.M1, 3)
    assert status == expected
    assert result == (bars if provider == "weltrade" else [])


@pytest.mark.parametrize("login,account,expected", [(4242, "4242", "FRESH"), (4242, "4243", "CONTEXT_MISMATCH"), (None, "4242", "CONTEXT_MISMATCH")])
async def test_risk_requires_configured_account_match(service, monkeypatch, login, account, expected):
    monkeypatch.setattr(settings, "weltrade_demo_login", login)
    now = datetime.now(timezone.utc)
    snapshot = RiskAuthorizationSnapshot(
        observed_at=now, broker="weltrade", environment="development",
        account_id=account, evaluation_state=RiskEvaluationState.AUTHORIZED,
        balance=100.0, equity=100.0, currency="USD", max_daily_loss=2.0,
        max_trades_daily=5, daily_trades_count=1, daily_loss_percent=0.25,
        risk_allowed=True, risk_message="Limits OK", rejection_reason="",
        authorized_risk_amount=0.5, authorized_risk_percent=0.5,
        execution_quantity_available=True, execution_quantity_value=0.01,
        execution_quantity_unit="MT5_LOTS", execution_quantity_reason="Fixture sizing",
    )
    store = SQLiteExecutionSafetyStore(settings.execution_safety_store_path, initialize=True)
    store.publish_risk(snapshot)
    with patch("api.service.utc_now", return_value=now):
        response = await service.get_risk_status()
    assert response.observation_status == expected
    assert response.execution_quantity_available is (expected == "FRESH")
    assert response.risk_authorized is (expected == "FRESH")
    if expected != "FRESH":
        assert response.balance == 0
        assert response.execution_quantity_value is None
    assert store.read_risk() == snapshot
    service._gateway.connect.assert_not_awaited()
    service._gateway.submit_order.assert_not_awaited()
