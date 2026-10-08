from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from backtesting.entry_quality import eligibility, summarize
from backtesting.models import BacktestTrade, BacktestExitReason
from broker.types import Candle, ExecutionQuantity, ExecutionQuantityUnit, Timeframe
from core.exceptions import MarketDataError
from data.dataset import load_dataset_bundle


def test_retrieval_timestamp_must_cover_every_bar_close():
    candles, manifest = load_dataset_bundle(Path("data/bundles/FX_Vol_20_M5"))
    assert eligibility(candles, manifest) is None  # gaps disclosed, never filled
    invalid = replace(manifest, retrieved_at=candles[-1].time + timedelta(seconds=299))
    assert "closes after" in eligibility(candles, invalid)
    assert eligibility(candles, replace(manifest, retrieved_at=candles[-1].time + timedelta(seconds=300))) is None


def test_native_provider_identity_cannot_be_substituted():
    candles, manifest = load_dataset_bundle(Path("data/bundles/FX_Vol_20_M5"))
    assert "mismatch" in eligibility(candles, replace(manifest, provider="deriv"))
    assert "mismatch" in eligibility(candles, replace(manifest, provider_symbol="R_20"))
    with pytest.raises(MarketDataError):
        eligibility(candles, replace(manifest, canonical_symbol="R_20"))


def test_metrics_use_net_initial_risk_and_include_entry_and_exit_bars():
    from datetime import datetime, timezone
    times = [datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=5*i) for i in range(4)]
    candles = [Candle(time=t, open=100, high=110, low=94, close=100, source="fixture") for t in times]
    trade = BacktestTrade(1, "FX Vol 20", Timeframe.M5, "BUY", times[0], times[1], 100,
                          times[2], 110, 90, 120,
                          ExecutionQuantity(value=1, unit=ExecutionQuantityUnit.SIMULATION_UNITS),
                          10, 1, 9, 100, 109, 2, BacktestExitReason.TIMEOUT)
    engine = SimpleNamespace(trades=[trade], decisions=[], result=SimpleNamespace(
        indicators=[SimpleNamespace(timestamp=t, ema50=100, atr=10, regime="TREND_UP", rsi=65) for t in times],
        maximum_drawdown=0, maximum_drawdown_percent=0))
    metrics = summarize(engine, candles, 0, 4)
    assert metrics["expectancy_account_currency"] is None
    assert metrics["expectancy_simulation_cash"] == 9
    assert metrics["expectancy_r"] == pytest.approx(.9)
    assert metrics["exposure_bar_fraction"] == .5
    assert metrics["mae_r_upper_bound"]["p50"] == pytest.approx(.6)
    assert metrics["mfe_r_upper_bound"]["p50"] == 1
