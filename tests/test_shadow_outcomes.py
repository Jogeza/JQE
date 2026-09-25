"""Safety and behaviour tests for the broker-order-free shadow resolver."""

from datetime import datetime, timedelta, timezone

from research.shadow_outcomes import (
    EXIT_GAP_AWARE,
    RESOLVER_VERSION,
    ENTRY_ASSUMPTION,
    ShadowBar,
    ShadowOutcomeStore,
    SignalSpec,
    estimate_adverse_overshoot_95,
    resolve_signal,
    structural_broker_order_free,
)
from broker.types import Timeframe


def _bar(minute: int, *, open_: float, high: float, low: float, close: float, spread: float = 0.1) -> ShadowBar:
    return ShadowBar(
        time=datetime(2026, 1, 1, 0, minute, tzinfo=timezone.utc),
        open=open_, high=high, low=low, close=close,
        spread_price=spread, source="fixture",
    )


def _signal(*, side: str = "BUY", horizon: int = 2) -> SignalSpec:
    return SignalSpec(
        signal_id=f"fixture-{side}", symbol="FX VOL 20", timeframe=Timeframe.M1,
        side=side, signal_close=datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
        stop_loss=99.0 if side == "BUY" else 101.0,
        take_profit=102.0 if side == "BUY" else 98.0,
        legacy_score=80, horizon_bars=horizon,
    )


def test_entry_is_next_candle_open_and_tp_includes_spread_cost():
    outcome = resolve_signal(
        _signal(),
        [_bar(1, open_=100.0, high=100.5, low=99.8, close=100.2), _bar(2, open_=100.0, high=102.1, low=99.9, close=101.0)],
        source="replay",
    )
    assert outcome.status == "TP"
    assert outcome.entry_assumption == ENTRY_ASSUMPTION
    assert outcome.entry_price == 100.1
    assert outcome.net_r == (102.0 - 100.1) / (100.1 - 99.0)
    assert outcome.resolver_version == RESOLVER_VERSION


def test_gap_aware_stop_uses_worse_executable_open():
    bars = [
        _bar(1, open_=100.0, high=100.5, low=99.8, close=100.2),
        _bar(2, open_=98.0, high=99.0, low=97.0, close=98.0),
    ]
    exact = resolve_signal(_signal(), bars, source="replay")
    gap = resolve_signal(_signal(), bars, source="replay", exit_mode=EXIT_GAP_AWARE, overshoot_price=0.25)
    assert exact.status == gap.status == "SL"
    assert exact.outcome_price == 99.0
    assert gap.outcome_price == 98.0
    assert gap.net_r < -1.0


def test_overshoot_percentile_uses_positive_adverse_excursions_only():
    bars = [
        _bar(1, open_=100.0, high=101.0, low=100.0, close=101.0),
        _bar(2, open_=100.0, high=101.0, low=100.0, close=101.0),
        _bar(3, open_=100.0, high=101.0, low=99.0, close=100.0),
        _bar(4, open_=100.0, high=101.0, low=97.0, close=100.0),
    ]
    assert estimate_adverse_overshoot_95(bars, side="BUY") == 2.9


def test_same_bar_collision_is_ambiguous_without_tick_order():
    outcome = resolve_signal(
        _signal(),
        [_bar(1, open_=100.0, high=103.0, low=98.0, close=100.0)],
        source="replay",
    )
    assert outcome.status == "AMBIGUOUS"


def test_timeout_is_marked_to_market_and_not_a_win():
    outcome = resolve_signal(
        _signal(horizon=1),
        [_bar(1, open_=100.0, high=100.5, low=99.8, close=100.5)],
        source="replay",
    )
    assert outcome.status == "TIMEOUT"
    assert outcome.net_r is not None


def test_missing_spread_fails_closed():
    bar = _bar(1, open_=100.0, high=100.5, low=99.8, close=100.2, spread=0.1)
    missing = ShadowBar(bar.time, bar.open, bar.high, bar.low, bar.close, None, "cache")
    outcome = resolve_signal(_signal(), [missing], source="replay")
    assert outcome.status == "UNRESOLVED"
    assert "spread" in (outcome.unresolved_reason or "")


def test_store_report_groups_by_side_timeframe_instrument_and_legacy_score(tmp_path):
    store = ShadowOutcomeStore(tmp_path / "shadow.sqlite3")
    outcome = resolve_signal(
        _signal(),
        [_bar(1, open_=100.0, high=100.5, low=99.8, close=100.2), _bar(2, open_=100.0, high=102.1, low=99.9, close=101.0)],
        source="replay",
    )
    store.upsert([outcome])
    report = store.report(source="replay")
    assert report["timeout_count"] == 0
    assert report["groups"][0]["legacy_score"] == "80"
    assert report["groups"][0]["status_counts"]["TP"] == 1
    assert report["groups"][0]["average_r_neutral"] == (102.0 - 100.1) / (100.1 - 99.0)
    assert report["r_basis"] == "PLAN_GEOMETRY"


def test_shadow_module_is_structurally_broker_order_free():
    assert structural_broker_order_free()
