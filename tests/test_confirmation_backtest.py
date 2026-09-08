"""Chronology and invariants for the close-confirmed research variant."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

import research.regime_diagnostics as diagnostics
from backtesting.models import BacktestExecutionAssumptions
from broker.types import Timeframe
from research.regime_diagnostics import ConfirmedEntryBacktestEngine


def _frame(regimes: tuple[str, ...] = (
    "NO_TRADE", "TREND_UP", "TREND_UP", "TREND_UP", "TREND_UP",
)) -> pd.DataFrame:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return pd.DataFrame({
        "time": [start + timedelta(minutes=15 * i) for i in range(len(regimes))],
        "open": [100.0, 101.0, 110.0, 111.0, 112.0][:len(regimes)],
        # Candle 1 deliberately spans both potential exits.  A position must not
        # exist there because its close supplies the confirmation observation.
        "high": [100.5, 150.0, 110.5, 111.5, 112.5][:len(regimes)],
        "low": [99.5, 50.0, 109.5, 110.5, 111.5][:len(regimes)],
        "close": [100.0, 101.0, 110.0, 111.0, 112.0][:len(regimes)],
        "ATR": [2.0] * len(regimes),
        "spread": [0.0] * len(regimes),
        "test_regime": list(regimes),
    })


@pytest.fixture(autouse=True)
def _deterministic_regime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        diagnostics,
        "detect_regime",
        lambda history: str(history.iloc[-1]["test_regime"]),
    )


def _engine() -> ConfirmedEntryBacktestEngine:
    return ConfirmedEntryBacktestEngine(
        starting_balance=1000.0,
        symbol="XAUUSD",
        timeframe=Timeframe.M15,
        execution=BacktestExecutionAssumptions(max_holding_candles=19),
    )


def test_confirmation_closes_at_i_plus_one_and_entry_is_i_plus_two() -> None:
    frame = _frame()
    engine = _engine()
    engine.queue_signal({"signal": "BUY", "confidence": 90}, 0, frame)

    engine.process_candle(1, frame)

    assert engine._position is None
    assert not engine.trades
    assert engine.decisions[-1].state == "CONFIRMATION_PASSED"
    assert engine.decisions[-1].candle_index == 1

    engine.process_candle(2, frame)

    assert engine._position is not None
    assert engine._position.entry_index == 2
    assert engine._position.entry_price == frame.iloc[2]["open"]
    assert engine._position.signal_index == 0


def test_failed_confirmation_expires_signal_without_entry() -> None:
    frame = _frame(("NO_TRADE", "RANGE", "TREND_UP", "TREND_UP"))
    engine = _engine()
    engine.queue_signal({"signal": "BUY", "confidence": 90}, 0, frame)

    engine.process_candle(1, frame)
    engine.process_candle(2, frame)

    assert engine.rejected_confirmations == 1
    assert engine._pending is None
    assert engine._position is None
    assert not engine.trades
    rejected = [d for d in engine.decisions if d.state == "CONFIRMATION_REJECTED"]
    assert len(rejected) == 1
    assert rejected[0].candle_index == 1


def test_confirmed_pending_signal_cannot_be_replaced() -> None:
    frame = _frame()
    engine = _engine()
    engine.queue_signal({"signal": "BUY", "confidence": 90}, 0, frame)
    engine.process_candle(1, frame)

    engine.queue_signal({"signal": "SELL", "confidence": 99}, 1, frame)
    engine.process_candle(2, frame)

    assert engine._position is not None
    assert engine._position.direction == "BUY"
    assert engine._position.signal_index == 0
    assert any(
        d.candle_index == 1
        and d.signal == "SELL"
        and d.state == "REJECTED_CANDIDATE"
        and "Entry already pending" in d.reasons
        for d in engine.decisions
    )


def test_delayed_entry_uses_actual_open_for_risk_plan() -> None:
    frame = _frame()
    engine = _engine()
    engine.queue_signal({"signal": "BUY", "confidence": 90}, 0, frame)
    engine.process_candle(1, frame)
    engine.process_candle(2, frame)

    position = engine._position
    assert position is not None
    assert position.entry_price == 110.0
    assert position.stop == 107.0
    assert position.target == 116.0
    expected_loss = (position.entry_price - position.stop) * position.quantity.value
    assert 0.0 < expected_loss <= 10.0 + 1e-9


def test_confirmation_on_final_candle_cannot_create_past_open_trade() -> None:
    frame = _frame(("NO_TRADE", "TREND_UP", "TREND_UP"))
    engine = _engine()
    engine.queue_signal({"signal": "BUY", "confidence": 90}, 1, frame)

    engine.process_candle(2, frame)
    assert engine._position is None
    assert engine.decisions[-1].state == "CONFIRMATION_PASSED"

    engine.finish(2, frame)

    assert engine._pending is None
    assert engine._confirmed_entry_index is None
    assert not engine.trades


def test_identical_event_sequences_are_deterministic() -> None:
    frame = _frame()

    def run_once() -> tuple[object, ...]:
        engine = _engine()
        engine.queue_signal({"signal": "BUY", "confidence": 90}, 0, frame)
        engine.process_candle(1, frame)
        engine.process_candle(2, frame)
        engine.process_candle(3, frame)
        engine.finish(4, frame)
        return tuple(engine.decisions), tuple(engine.trades), tuple(engine.equity_curve)

    assert run_once() == run_once()
