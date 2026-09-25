from datetime import datetime, timedelta, timezone

import numpy as np

from broker.types import Timeframe
from research.sequential_replay import (
    PersistedCandidate,
    SeriesArrays,
    build_random_specs,
    simulate_sequential,
)
from research.shadow_outcomes import signal_spec_from_setup
from research.shadow_outcomes import ShadowOutcome, SignalSpec


def _series(symbol: str = "FX VOL 20", count: int = 20) -> SeriesArrays:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    times = np.array([int((start + timedelta(minutes=i)).timestamp()) for i in range(count)], dtype=np.int64)
    prices = np.arange(100.0, 100.0 + count)
    return SeriesArrays(
        symbol=symbol, timeframe=Timeframe.M1, times=times,
        opens=prices, highs=prices + 2, lows=prices - 2, closes=prices + 1,
        spreads=np.full(count, 0.1), atr=np.full(count, 1.0), split_epoch=int(times[max(1, int(count * 0.6))]),
    )


def _candidate(signal_id: str, close_minute: int, outcome_minute: int, *, symbol: str = "FX VOL 20", status: str = "TP") -> PersistedCandidate:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    close = start + timedelta(minutes=close_minute)
    spec = SignalSpec(
        signal_id=signal_id, symbol=symbol, timeframe=Timeframe.M1,
        side="BUY", signal_close=close, stop_loss=98, take_profit=104,
        legacy_score=80,
    )
    outcome = ShadowOutcome(
        source="replay", signal_id=signal_id, symbol=symbol, timeframe="M1", side="BUY",
        legacy_score=80, institutional_score=None, signal_close=close,
        entry_time=start + timedelta(minutes=close_minute + 1), entry_price=100,
        stop_loss=98, take_profit=104, status=status, outcome_time=start + timedelta(minutes=outcome_minute),
        outcome_price=(104 if status == "TP" else 98), gross_r=(1 if status == "TP" else -1), spread_cost_price=0.1, net_r=(1 if status == "TP" else -1),
        unresolved_reason=None, ambiguity_detail=None,
    )
    return PersistedCandidate(spec, "exploration", outcome)


def test_sequential_replay_blocks_reentry_until_prior_trade_resolves():
    candidates = [_candidate("one", 0, 5), _candidate("two", 2, 7)]
    result = simulate_sequential(
        candidates, {("FX VOL 20", Timeframe.M1): _series()},
        horizon=20, global_cap=20, per_instrument_cap=20, use_stored_outcome=True,
    )
    assert result["accepted"] == 1
    assert result["skipped"]["open_position"] == 1


def test_sequential_replay_applies_global_and_instrument_caps():
    first = _candidate("one", 0, 1)
    second = _candidate("two", 2, 3)
    third = _candidate("three", 4, 5, symbol="SFX VOL 20")
    series = {
        ("FX VOL 20", Timeframe.M1): _series("FX VOL 20"),
        ("SFX VOL 20", Timeframe.M1): _series("SFX VOL 20"),
    }
    result = simulate_sequential(
        [first, second, third], series, horizon=20,
        global_cap=1, per_instrument_cap=1, use_stored_outcome=True,
    )
    assert result["accepted"] == 1
    assert result["skipped"]["global_daily_cap"] == 2


def test_random_control_uses_same_trade_plan_geometry():
    generated = build_random_specs(
        _series(count=300), count=5, side_counts={"BUY": 5}, seed=7, horizon=2,
    )
    assert generated
    assert all(item.spec.side == "BUY" for item in generated)
    assert all(item.spec.take_profit > item.spec.stop_loss for item in generated)


def test_old_dashboard_expiry_does_not_retire_the_predeclared_horizon():
    spec = signal_spec_from_setup("setup-1", {
        "direction": "BUY", "timeframe": "M1", "candle_close_time": "2026-01-01T00:00:00+00:00",
        "stop_loss": 98, "targets": [104], "symbol": "FX VOL 20",
        "expires_at": "2026-01-01T00:01:00+00:00",
    })
    assert spec is not None
    assert spec.horizon_bars == 20


def test_sequential_safety_variants_fail_closed_after_their_declared_limit():
    candidates = [_candidate(str(index), index * 3, index * 3 + 1, status="SL") for index in range(8)]
    series = {("FX VOL 20", Timeframe.M1): _series(count=300)}
    daily = simulate_sequential(
        candidates, series, horizon=20, global_cap=20, per_instrument_cap=20,
        use_stored_outcome=True, daily_loss_stop=-0.5,
    )
    assert daily["skipped"]["daily_loss_stop"] >= 1
    breaker = simulate_sequential(
        candidates, series, horizon=20, global_cap=20, per_instrument_cap=20,
        use_stored_outcome=True, consecutive_loss_breaker=2,
    )
    assert breaker["sequential_variants"]["consecutive_loss_breaker"] == 2
