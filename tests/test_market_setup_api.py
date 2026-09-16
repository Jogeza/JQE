"""Unified market-setup and offline dashboard paper-execution tests."""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from api.service import ApplicationService
from broker.simulation_gateway import SimulationGateway
from broker.types import Candle, ExecutionQuantity, ExecutionQuantityUnit, OrderRequest, OrderSide, Timeframe
from config.settings import settings
from data.active_market import freshness_facts
from execution.safety import EmergencyStopState
from execution.dashboard_paper import DashboardPaperGateway, DashboardPaperStore
from execution.simulation_daily_guard import SQLiteSimulationDailySubmissionGuard
from intelligence.confidence_model import ConfidenceBreakdown
from intelligence.trade_plan import TradePlan
from risk.risk_engine import RiskEngine


def test_volatility_75_uses_continuous_weekend_freshness() -> None:
    observed_at = datetime(2026, 9, 13, 9, 36, tzinfo=timezone.utc)
    candle = Candle(
        time=observed_at - timedelta(minutes=6),
        open=100,
        high=101,
        low=99,
        close=100,
        source="deriv",
    )

    latest, expected, age, state, reasons = freshness_facts(
        [candle],
        symbol="R_75",
        timeframe=Timeframe.M5,
        observed_at=observed_at,
        cache_only=False,
    )

    assert latest == observed_at - timedelta(minutes=1)
    assert expected == observed_at.replace(minute=35)
    assert age == 0
    assert state == "FRESH"
    assert reasons == ["LATEST_CLOSED_CANDLE_WITHIN_TOLERANCE"]


@pytest.mark.asyncio
async def test_no_trade_is_a_visible_blocked_setup(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "dashboard_paper_store_path", tmp_path / "paper.sqlite3")
    monkeypatch.setattr(settings, "dashboard_paper_intent_store_path", tmp_path / "intents.sqlite3")
    monkeypatch.setattr(settings, "simulation_daily_submission_store_path", tmp_path / "daily.sqlite3")
    monkeypatch.setattr(settings, "market_data_source", "simulation")
    service = ApplicationService(gateway=SimulationGateway(seed=41))
    setup = await service.get_market_setup("XAUUSD", "M5", 80)

    assert setup.direction in {"BUY", "SELL", "NO_TRADE"}
    assert setup.confidence_score == sum(item.score for item in setup.evidence)
    assert setup.historical_win_rate.status == "UNAVAILABLE"
    assert setup.data_freshness.age_seconds <= setup.data_freshness.maximum_age_seconds, (
        setup.observed_at, setup.candle_close_time, setup.data_freshness
    )
    if setup.direction == "NO_TRADE":
        assert setup.setup_state == "BLOCKED", setup.model_dump()
        assert "NO_TRADE" in setup.reason_codes


@pytest.mark.asyncio
async def test_ready_setup_executes_once_through_offline_paper_boundary(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "dashboard_paper_store_path", tmp_path / "paper.sqlite3")
    monkeypatch.setattr(settings, "dashboard_paper_intent_store_path", tmp_path / "intents.sqlite3")
    monkeypatch.setattr(settings, "simulation_daily_submission_store_path", tmp_path / "daily.sqlite3")
    monkeypatch.setattr(settings, "market_data_source", "simulation")
    monkeypatch.setattr(settings, "emergency_stop", EmergencyStopState.CLEAR)
    breakdown = ConfidenceBreakdown(
        trend_score=25, structure_score=20, liquidity_score=20,
        momentum_score=15, volatility_score=10, risk_score=10, total=100,
        factors={
            "trend": "BULLISH", "structure": "CONFIRMED", "liquidity": "GOOD",
            "momentum": "STRONG", "volatility": "MEDIUM", "risk": "FAVORABLE",
        },
    )
    plan = TradePlan(
        symbol="XAUUSD", signal="BUY", confidence=100, entry=100,
        stop_loss=98, take_profit=104, risk_reward=2,
        invalidation="Price closes below 98", regime="TRENDING",
    )
    decision = {
        "signal": "BUY", "confidence": 100, "quality": "HIGH", "score": 100,
        "reasons": ["trend aligned"], "intelligence": {"regime": "TRENDING"},
        "confidence_breakdown": breakdown, "trade_plan": plan,
    }
    service = ApplicationService(
        gateway=SimulationGateway(seed=11),
        risk_engine=RiskEngine(min_atr=0, min_confidence=75),
    )
    with patch("api.service.generate_trading_signal", return_value=decision):
        setup = await service.get_market_setup("XAUUSD", "M5", 80)

    assert setup.setup_state == "READY", setup.model_dump()
    assert setup.risk_authorization.status == "AUTHORIZED"
    assert setup.execution_authorization.status == "AUTHORIZED"
    payload = json.loads(setup.model_dump_json())
    assert isinstance(payload["entry_price"], str)
    assert isinstance(payload["risk_authorization"]["quantity"], str)

    auth = setup.execution_authorization
    direct_guard = SQLiteSimulationDailySubmissionGuard(tmp_path / "direct-daily.sqlite3", limit=5)
    direct = await DashboardPaperGateway(
        DashboardPaperStore(settings.dashboard_paper_store_path), setup,
        direct_guard,
        "simulation:DIRECT-TEST",
    ).submit_order(
        OrderRequest(
            symbol=setup.symbol, side=OrderSide.BUY,
            quantity=ExecutionQuantity(value=float(auth.quantity), unit=ExecutionQuantityUnit.SIMULATION_UNITS),
            stop_loss=float(setup.stop_loss), take_profit=float(setup.targets[0]),
            idempotency_key="direct-paper-check",
        )
    )
    assert direct.status.value == "FILLED"
    assert direct_guard.status("simulation:DIRECT-TEST").count == 1

    first = await service.execute_market_setup(setup.setup_id)
    second = await service.execute_market_setup(setup.setup_id)

    assert first.status == "OPENED"
    assert first.paper_only is True
    assert first.order_id is not None and first.order_id.startswith("PAPER-C-")
    assert second.status == "ALREADY_RECORDED"
    assert second.outcome_id == first.outcome_id
