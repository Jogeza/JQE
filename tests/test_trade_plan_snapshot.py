"""Tests for durable trade-plan facts attached to SIGNAL events."""

from datetime import datetime, timezone

from intelligence.trade_plan import TradePlan
from research.trade_plan_snapshot import (
    ENTRY_BASIS,
    SPREAD_SOURCE,
    TRADE_PLAN_SNAPSHOT_VERSION,
    build_trade_plan_snapshot,
)


def test_actionable_signal_persists_complete_plan_and_explicit_entry_basis():
    plan = TradePlan(
        symbol="FX VOL 20", signal="BUY", confidence=80, quality="HIGH",
        score=80, entry_type="MARKET", entry=100.0, stop_method="ATR",
        stop_loss=99.0, target_rr=2.0, take_profit=102.0, risk_reward=2.0,
        atr=0.666, trend="BULLISH", momentum="STRONG", volatility="NORMAL",
        liquidity="GOOD", regime="TRENDING",
    )
    snapshot = build_trade_plan_snapshot(
        signal={"signal": "BUY", "trade_plan": plan},
        symbol="FX VOL 20", timeframe="M5",
        signal_candle_open=datetime(2026, 9, 24, 8, 0, tzinfo=timezone.utc),
        signal_candle_close=datetime(2026, 9, 24, 8, 5, tzinfo=timezone.utc),
    )
    assert snapshot["schema_version"] == TRADE_PLAN_SNAPSHOT_VERSION
    assert snapshot["status"] == "ACTIONABLE"
    assert snapshot["entry_basis"]["kind"] == ENTRY_BASIS
    assert snapshot["entry_basis"]["fill_price"] is None
    assert snapshot["stop_loss"] == 99.0
    assert snapshot["take_profit"] == 102.0
    assert snapshot["spread"]["source"] == SPREAD_SOURCE
    assert snapshot["plan"]["entry"] == 100.0


def test_non_actionable_signal_still_persists_schema_and_missing_plan_reason():
    snapshot = build_trade_plan_snapshot(
        signal={"signal": "NO_TRADE", "confidence": 61},
        symbol="FX VOL 20", timeframe="M5",
        signal_candle_open="2026-09-24T08:00:00+00:00",
        signal_candle_close="2026-09-24T08:05:00+00:00",
    )
    assert snapshot["status"] == "NON_ACTIONABLE"
    assert snapshot["entry_basis"]["kind"] == ENTRY_BASIS
    assert snapshot["stop_loss"] is None
    assert snapshot["take_profit"] is None
    assert snapshot["reason"] == "SIGNAL_PAYLOAD_DID_NOT_INCLUDE_TRADE_PLAN"

