from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from broker.types import ExecutionQuantity, ExecutionQuantityUnit, OrderSide
from execution.policy import ExecutionDecisionCode, ExecutionIntent, ExecutionPolicy
from research.historical_confirmation import HistoricalConfirmationState
from research.historical_safety import (
    ExecutionContextKind, HistoricalResearchSafetyContext,
    require_historical_research_context,
)


def _safety() -> HistoricalResearchSafetyContext:
    return HistoricalResearchSafetyContext(
        kind=ExecutionContextKind.HISTORICAL_RESEARCH, symbol="XAUUSD",
        max_daily_loss_percent=5.0, max_daily_trades=20,
    )


def _intent() -> ExecutionIntent:
    return ExecutionIntent(
        symbol="XAUUSD", side=OrderSide.BUY,
        quantity=ExecutionQuantity(value=1.0, unit=ExecutionQuantityUnit.SIMULATION_UNITS),
        authorized_risk_amount=1.0, expected_loss_at_stop=1.0,
        quantity_risk_verified=True, entry=100.0, stop_loss=99.0,
        take_profit=102.0, idempotency_key="research:1", risk_approved=True,
    )


def test_explicit_historical_context_is_deterministic_and_policy_compatible() -> None:
    safety = _safety()
    assert safety.kind is ExecutionContextKind.HISTORICAL_RESEARCH
    assert safety.assumptions["broker_execution_enabled"] is False
    assert ExecutionPolicy.evaluate(_intent(), safety.execution_context()).code is ExecutionDecisionCode.ALLOWED


def test_missing_or_runtime_research_context_fails_closed() -> None:
    with pytest.raises(ValueError, match="required"):
        require_historical_research_context(None)
    with pytest.raises(ValueError, match="HISTORICAL_RESEARCH"):
        HistoricalResearchSafetyContext(
            kind=ExecutionContextKind.RUNTIME_EXECUTION, symbol="XAUUSD",
            max_daily_loss_percent=5.0, max_daily_trades=20,
        )


def test_runtime_unknown_policy_behavior_remains_fail_closed() -> None:
    context = replace(_safety().execution_context(), emergency_stop=None)
    assert ExecutionPolicy.evaluate(_intent(), context).code is ExecutionDecisionCode.SAFETY_CONTEXT_INVALID


def test_confirmation_state_enforces_i_i1_i2_and_prevents_duplicates() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    interval = timedelta(minutes=15)
    state = HistoricalConfirmationState()
    queued = state.queue(
        symbol="XAUUSD", timeframe="M15", signal_candle=start,
        direction="BUY", confidence=80, strategy_context={"regime": "TREND_UP"},
        candle_interval=interval,
    )
    assert queued.state == "STRATEGY_CANDIDATE"
    confirmed = state.observe(start + interval, "TREND_UP")
    assert confirmed.state == "CONFIRMED"
    duplicate = state.observe(start + interval, "TREND_UP")
    assert duplicate.state == "DUPLICATE_CONFIRMATION_PREVENTED"
    assert state.observe(start + interval * 2, "TREND_UP").state == "ENTRY_DUE"


def test_missing_confirmation_and_entry_candles_do_not_shift() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    interval = timedelta(minutes=15)
    state = HistoricalConfirmationState()
    state.queue(symbol="XAUUSD", timeframe="M15", signal_candle=start,
                direction="BUY", confidence=80, strategy_context={}, candle_interval=interval)
    assert state.observe(start + interval * 2, "TREND_UP").reason == "MISSING_CONFIRMATION_CANDLE"

    state.queue(symbol="XAUUSD", timeframe="M15", signal_candle=start,
                direction="BUY", confidence=80, strategy_context={}, candle_interval=interval)
    state.observe(start + interval, "TREND_UP")
    assert state.observe(start + interval * 3, "TREND_UP").reason == "MISSING_ENTRY_CANDLE"


def test_pending_state_round_trips_for_resume(tmp_path) -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    state = HistoricalConfirmationState()
    state.queue(symbol="XAUUSD", timeframe="M15", signal_candle=start,
                direction="SELL", confidence=80, strategy_context={"regime": "TREND_DOWN"},
                candle_interval=timedelta(minutes=15))
    path = tmp_path / "pending.json"
    state.save(path)
    restored = HistoricalConfirmationState.load(path)
    assert restored.pending == state.pending


def test_campaign_boundary_is_incomplete_not_failed() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    state = HistoricalConfirmationState()
    state.queue(symbol="XAUUSD", timeframe="M15", signal_candle=start,
                direction="BUY", confidence=80, strategy_context={},
                candle_interval=timedelta(minutes=15))
    assert state.finish().state == "INCOMPLETE_CONFIRMATION"
