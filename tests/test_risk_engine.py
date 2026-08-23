"""Tests for risk.risk_engine and risk.position_sizing."""

from __future__ import annotations

import pandas as pd
import pytest

from risk.position_sizing import PositionSizing, calculate_position_size
from risk.risk_engine import (
    MAX_RISK_PERCENT,
    MAX_SPREAD,
    MIN_ATR,
    MIN_CONFIDENCE,
    RiskEngine,
)


def _market_data(atr: float = 2.0, spread: float = 5.0) -> pd.DataFrame:
    return pd.DataFrame({"close": [100.0], "ATR": [atr], "spread": [spread]})


class TestRiskEngine:
    def test_initialization_defaults(self) -> None:
        engine = RiskEngine()
        assert engine.min_confidence == MIN_CONFIDENCE
        assert engine.max_risk_percent == MAX_RISK_PERCENT
        assert engine.min_atr == MIN_ATR
        assert engine.max_spread == MAX_SPREAD

    def test_approve_trade_valid(self) -> None:
        engine = RiskEngine()
        decision = engine.approve_trade(
            signal={"signal": "BUY", "confidence": 85},
            market_data=_market_data(atr=2.5, spread=10.0),
            balance=1000.0,
        )
        assert decision["approved"] is True
        assert decision["risk_percent"] == MAX_RISK_PERCENT
        assert decision["lot_size"] > 0.0

    def test_reject_low_confidence(self) -> None:
        engine = RiskEngine(min_confidence=80)
        decision = engine.approve_trade(
            signal={"signal": "BUY", "confidence": 75},
            market_data=_market_data(),
        )
        assert decision["approved"] is False
        assert "Confidence too low" in decision["reason"]

    def test_daily_trade_limit_enforcement(self) -> None:
        engine = RiskEngine(max_trades_daily=2)
        # 2 trades
        engine.record_trade_execution()
        engine.record_trade_execution()

        decision = engine.approve_trade(
            signal={"signal": "BUY", "confidence": 90},
            market_data=_market_data(),
            enforce_limits=True,
        )
        assert decision["approved"] is False
        assert "Daily trade limit reached" in decision["reason"]

        # Reset daily stats
        engine.reset_daily_stats()
        decision_after_reset = engine.approve_trade(
            signal={"signal": "BUY", "confidence": 90},
            market_data=_market_data(),
            enforce_limits=True,
        )
        assert decision_after_reset["approved"] is True

    def test_daily_loss_limit_enforcement(self) -> None:
        engine = RiskEngine(max_daily_loss=3.0)
        engine.record_loss(3.5)

        decision = engine.approve_trade(
            signal={"signal": "BUY", "confidence": 90},
            market_data=_market_data(),
            enforce_limits=True,
        )
        assert decision["approved"] is False
        assert "Daily maximum loss limit reached" in decision["reason"]


class TestPositionSizingEngine:
    def test_position_sizing_class_bounds(self) -> None:
        sizer = PositionSizing(min_lot=0.02, max_lot=5.0)
        # Very small risk -> bounded to min_lot
        assert sizer.calculate_lot(risk_amount=0.01, stop_distance=100.0) == 0.02
        # Very large risk -> bounded to max_lot
        assert sizer.calculate_lot(risk_amount=10000.0, stop_distance=1.0) == 5.0
        # Invalid stop distance -> 0.0
        assert sizer.calculate_lot(risk_amount=100.0, stop_distance=0) == 0.0
