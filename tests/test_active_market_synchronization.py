import pytest
from datetime import datetime, timezone
from decimal import Decimal

from broker.types import Candle, Timeframe
from core.exceptions import MarketDataError
from data.active_market import (
    expected_latest_closed_candle_at,
    freshness_facts,
    is_continuous_market,
    symbol_display_name,
)
from execution.market_setup import (
    resolve_historical_win_rate,
    MarketSetup,
    DataFreshnessDTO,
    SetupAuthorizationDTO,
    MarketLevelDTO,
)
from api.service import _resolve_timeframe


def test_resolve_timeframe_strict():
    """Verify strictly resolving timeframe without silent fallback."""
    assert _resolve_timeframe("H1") == Timeframe.H1
    assert _resolve_timeframe("M5") == Timeframe.M5
    assert _resolve_timeframe("M15") == Timeframe.M15
    assert _resolve_timeframe("D1") == Timeframe.D1

    # Invalid timeframe must raise MarketDataError, not silently fall back to M5
    with pytest.raises(MarketDataError) as exc_info:
        _resolve_timeframe("INVALID_TF")
    assert "Unsupported timeframe" in str(exc_info.value)


def test_continuous_vs_fx_market_classification():
    """Verify synthetic continuous markets vs 24/5 FX/metal markets."""
    assert is_continuous_market("R_75") is True
    assert is_continuous_market("1HZ75V") is True
    assert is_continuous_market("XAUUSD") is False
    assert is_continuous_market("EURUSD") is False


def test_weekend_fx_closed_candle_expectation():
    """Verify weekend FX candle expectation maps to Friday 22:00 UTC."""
    # Saturday 14:00 UTC
    sat = datetime(2026, 9, 12, 14, 0, 0, tzinfo=timezone.utc)
    expected_xau = expected_latest_closed_candle_at(sat, Timeframe.H1, "XAUUSD")
    # Friday close at 22:00 UTC
    assert expected_xau == datetime(2026, 9, 11, 22, 0, 0, tzinfo=timezone.utc)

    # For continuous market on Saturday, it is the exact prior hour close
    expected_r75 = expected_latest_closed_candle_at(sat, Timeframe.H1, "R_75")
    assert expected_r75 == datetime(2026, 9, 12, 14, 0, 0, tzinfo=timezone.utc)


def test_freshness_facts_evaluation():
    """Verify fresh vs stale facts calculation against tolerance."""
    now = datetime(2026, 9, 13, 12, 5, 0, tzinfo=timezone.utc)
    # Candle starting at 11:00 UTC closes at 12:00 UTC for H1
    candle = Candle(
        time=datetime(2026, 9, 13, 11, 0, 0, tzinfo=timezone.utc),
        open=100.0, high=105.0, low=99.0, close=102.0, volume=1000.0
    )

    # Fresh candle (age 5 min <= tolerance 1h)
    latest, expected, age, state, reasons = freshness_facts(
        [candle], symbol="R_75", timeframe=Timeframe.H1, observed_at=now, cache_only=False
    )
    assert state == "FRESH"
    assert age == Decimal("0")
    assert "LATEST_CLOSED_CANDLE_WITHIN_TOLERANCE" in reasons

    # Old candle (starting at 09:00 UTC, closed at 10:00 UTC)
    old_candle = Candle(
        time=datetime(2026, 9, 13, 9, 0, 0, tzinfo=timezone.utc),
        open=100.0, high=105.0, low=99.0, close=102.0, volume=1000.0
    )
    _lat, _exp, old_age, old_state, old_reasons = freshness_facts(
        [old_candle], symbol="R_75", timeframe=Timeframe.H1, observed_at=now, cache_only=False
    )
    assert old_state == "STALE"
    assert "LATEST_CLOSED_CANDLE_LATE" in old_reasons


def test_historical_win_rate_grounded_isolation():
    """Verify that H1 historical win rate is UNAVAILABLE when only M15 experiments exist."""
    win_rate = resolve_historical_win_rate("XAUUSD", "H1")
    assert win_rate.status == "UNAVAILABLE"
    assert win_rate.win_rate_percent is None
    assert "No compatible out-of-sample evidence" in win_rate.reason


def test_symbol_display_name():
    """Verify friendly display names."""
    assert symbol_display_name("XAUUSD") == "Gold / US Dollar"
    assert symbol_display_name("EURUSD") == "Euro / US Dollar"
    assert symbol_display_name("R_75") == "Volatility 75 Index"


def test_market_setup_no_trade_contract():
    """Verify NO_TRADE setup contains no fabricated prices and clean state."""
    setup = MarketSetup(
        setup_id="setup-12345",
        symbol="XAUUSD",
        timeframe="H1",
        observed_at=datetime.now(timezone.utc),
        candle_close_time=datetime.now(timezone.utc),
        direction="NO_TRADE",
        setup_state="FORMING",
        entry_price=None,
        stop_loss=None,
        targets=[],
        levels=[MarketLevelDTO(kind="SUPPORT", price=Decimal("2500.00"), method="RECENT_RANGE_20_V1")],
        confidence_score=40,
        confidence_method="6-factor confluence",
        evidence=[],
        conflicts=["TREND_MOMENTUM_MISMATCH"],
        market_regime="RANGE",
        data_freshness=DataFreshnessDTO(
            status="CURRENT",
            source="SIMULATION",
            maximum_age_seconds=3600,
            reason="Fresh closed candle",
            freshness_state="FRESH",
        ),
        risk_authorization=SetupAuthorizationDTO(
            status="BLOCKED",
            reason="No executable direction",
        ),
        execution_authorization=SetupAuthorizationDTO(
            status="BLOCKED",
            reason="No executable direction",
        ),
        reason_codes=["NO_ACTIONABLE_SIGNAL"],
    )
    assert setup.direction == "NO_TRADE"
    assert setup.entry_price is None
    assert setup.stop_loss is None
    assert len(setup.targets) == 0
    assert len(setup.levels) == 1
    assert setup.levels[0].kind == "SUPPORT"
