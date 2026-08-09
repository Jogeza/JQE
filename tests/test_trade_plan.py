from __future__ import annotations

import pandas as pd
import pytest

from intelligence.trade_plan import TradePlan, TradePlanBuilder
from core.indicators import calculate_indicators
from strategy.features.feature_engine import FeatureEngine
from intelligence.market_regime import detect_regime
from strategy.signal_engine import SignalEngine


@pytest.fixture
def base_intelligence():
    return {
        "trend": "BULLISH",
        "momentum": "STRONG",
        "volatility": "NORMAL",
        "liquidity": "GOOD",
        "regime": "TRENDING",
        "atr": 10.0,
        "rsi": 60,
    }


@pytest.fixture
def base_signal():
    return {
        "signal": "BUY",
        "confidence": 85,
        "quality": "GOOD",
        "score": 80,
        "reasons": ["Good trend", "Strong momentum"],
    }


def test_valid_buy_plan(base_intelligence, base_signal):
    builder = TradePlanBuilder(min_rr=1.5, atr_sl_multiplier=1.5, target_rr=2.0)
    plan = builder.build("BTCUSD", base_intelligence, base_signal, price=100.0, account_balance=1000.0)

    assert plan.is_valid()
    assert plan.signal == "BUY"
    assert plan.entry == 100.0
    # SL = 100 - (10 * 1.5) = 85.0
    assert plan.stop_loss == 85.0
    # TP = 100 + (10 * 1.5 * 2.0) = 130.0
    assert plan.take_profit == 130.0
    
    # Check BUY invariants: SL < entry < TP
    assert plan.stop_loss < plan.entry < plan.take_profit
    
    # Check RR
    risk = plan.entry - plan.stop_loss
    reward = plan.take_profit - plan.entry
    assert plan.risk_reward == pytest.approx(reward / risk)
    
    assert plan.position_size is not None


def test_valid_sell_plan(base_intelligence, base_signal):
    base_signal["signal"] = "SELL"
    base_intelligence["trend"] = "BEARISH"
    
    builder = TradePlanBuilder()
    plan = builder.build("EURUSD", base_intelligence, base_signal, price=1.1000, account_balance=1000.0)

    assert plan.is_valid()
    assert plan.signal == "SELL"
    assert plan.entry == 1.1000
    # SL = 1.1 + (10 * 1.5) = 16.1
    assert plan.stop_loss == 16.1000
    # TP = 1.1 - (10 * 1.5 * 2.0) = -28.9
    assert plan.take_profit == -28.9000
    
    # Check SELL invariants: TP < entry < SL
    assert plan.take_profit < plan.entry < plan.stop_loss


def test_no_trade_missing_price(base_intelligence, base_signal):
    builder = TradePlanBuilder()
    plan = builder.build("BTCUSD", base_intelligence, base_signal, price=0.0)

    assert not plan.is_valid()
    assert plan.signal == "NO_TRADE"
    assert plan.entry is None
    assert plan.stop_loss is None
    assert plan.take_profit is None
    assert "Rejected: Invalid or unavailable market price" in plan.reasons


def test_no_trade_missing_atr(base_intelligence, base_signal):
    base_intelligence["atr"] = 0
    builder = TradePlanBuilder()
    plan = builder.build("BTCUSD", base_intelligence, base_signal, price=100.0)

    assert not plan.is_valid()
    assert plan.signal == "NO_TRADE"
    assert plan.entry is None
    assert plan.stop_loss is None
    assert "Rejected: Cannot calculate ATR-based stops (Invalid ATR)" in plan.reasons


def test_minimum_rr_gating(base_intelligence, base_signal):
    # Ask for target_rr of 1.0, but min_rr is 1.5
    builder = TradePlanBuilder(min_rr=1.5, target_rr=1.0)
    plan = builder.build("BTCUSD", base_intelligence, base_signal, price=100.0)

    assert not plan.is_valid()
    assert plan.signal == "NO_TRADE"
    assert "Rejected: Risk/reward (1.0) below minimum threshold (1.5)" in plan.reasons


def test_warnings_propagation(base_intelligence, base_signal):
    base_intelligence["liquidity"] = "LOW"
    base_intelligence["volatility"] = "HIGH"
    base_intelligence["rsi"] = 75
    
    builder = TradePlanBuilder()
    plan = builder.build("BTCUSD", base_intelligence, base_signal, price=100.0)

    assert "Low liquidity" in plan.warnings
    assert "High volatility" in plan.warnings
    assert "Elevated RSI (Overbought)" in plan.warnings


@pytest.mark.parametrize("price, direction, atr", [
    (100.0, "BUY", 5.0),
    (50.0, "BUY", 1.2),
    (1.1, "SELL", 0.005),
    (1500.0, "SELL", 20.0),
])
def test_property_style_safety(price, direction, atr):
    """Guarantees directional invariants are never violated for valid trades."""
    builder = TradePlanBuilder(min_rr=1.5, atr_sl_multiplier=1.5, target_rr=2.0)
    intelligence = {"atr": atr, "trend": "BULLISH" if direction == "BUY" else "BEARISH"}
    signal_dict = {"signal": direction}
    
    plan = builder.build("SYM", intelligence, signal_dict, price=price)
    
    assert plan.is_valid()
    if direction == "BUY":
        assert plan.stop_loss < plan.entry < plan.take_profit
    else:
        assert plan.take_profit < plan.entry < plan.stop_loss


def test_scanner_to_trade_plan_integration():
    """Scanner Integration Test: proves data -> intelligence -> signal -> plan works."""
    df = pd.DataFrame(
        {
            "close": [100.0] * 15,
            "high": [101.0] * 15,
            "low": [99.0] * 15,
        }
    )
    df = calculate_indicators(df)
    
    # FeatureEngine creates intelligence
    fe = FeatureEngine()
    intelligence = fe.analyze(df)
    intelligence["regime"] = detect_regime(df)
    
    # SignalEngine uses intelligence
    se = SignalEngine()
    signal = se.generate(intelligence)
    
    # Builder ties it together
    builder = TradePlanBuilder()
    plan = builder.build("TEST", intelligence, signal, price=100.0)
    
    assert isinstance(plan, TradePlan)
    assert plan.signal in ("BUY", "SELL", "NO_TRADE")
