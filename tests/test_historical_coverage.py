from argparse import Namespace
from datetime import datetime, timedelta, timezone

import pytest

from backtesting import run as research_cli
from broker.types import Candle, Timeframe
from core.exceptions import MarketDataError
from data.coverage import (
    DerivXauUsdM15CoveragePolicy,
    validate_historical_coverage,
)
from data.storage import CandleStore


UTC = timezone.utc


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _fixture(start: datetime, end: datetime) -> list[Candle]:
    policy = DerivXauUsdM15CoveragePolicy()
    candles = []
    timestamp = start
    index = 0
    while timestamp <= end:
        if policy.is_candle_expected(timestamp):
            base = 2600.0 + index * 0.1
            candles.append(Candle(time=timestamp, open=base, high=base + 1,
                                  low=base - 1, close=base + 0.2,
                                  source="deriv"))
        timestamp += timedelta(minutes=15)
        index += 1
    return candles


def _validate(candles, start, end):
    return validate_historical_coverage(
        candles, provider="deriv", canonical_symbol="XAUUSD",
        provider_symbol="frxXAUUSD", timeframe=Timeframe.M15,
        start=start, end=end,
    )


def test_daily_closure_boundaries_are_exact() -> None:
    policy = DerivXauUsdM15CoveragePolicy()
    assert policy.is_candle_expected(_dt("2026-08-24T20:45:00Z"))
    assert not policy.is_candle_expected(_dt("2026-08-24T21:00:00Z"))
    assert not policy.is_candle_expected(_dt("2026-08-24T21:45:00Z"))
    assert policy.is_candle_expected(_dt("2026-08-24T22:00:00Z"))
    assert policy.is_candle_expected(_dt("2026-08-24T22:15:00Z"))


def test_observed_closure_is_accepted_but_active_gap_is_rejected() -> None:
    start, end = _dt("2026-08-24T20:30:00Z"), _dt("2026-08-24T22:15:00Z")
    candles = _fixture(start, end)
    result = _validate(candles, start, end)
    assert result.is_complete
    assert result.legitimate_closed_count == 4
    missing = [c for c in candles if c.time != _dt("2026-08-24T20:30:00Z")]
    result = _validate(missing, start, end)
    assert result.missing_count == 1
    assert result.first_missing == _dt("2026-08-24T20:30:00Z")


def test_multiday_and_weekend_policy() -> None:
    start, end = _dt("2026-08-28T20:30:00Z"), _dt("2026-08-30T22:15:00Z")
    candles = _fixture(start, end)
    result = _validate(candles, start, end)
    assert result.is_complete
    assert result.legitimate_closed_count > 0
    assert {c.time for c in candles} == {
        _dt("2026-08-28T20:30:00Z"), _dt("2026-08-28T20:45:00Z"),
    }


def test_juneteenth_early_close_is_explicit_not_a_generic_gap() -> None:
    policy = DerivXauUsdM15CoveragePolicy()
    assert policy.is_candle_expected(_dt("2026-06-19T17:00:00Z"))
    assert not policy.is_candle_expected(_dt("2026-06-19T17:15:00Z"))
    assert not policy.is_candle_expected(_dt("2026-06-19T20:45:00Z"))


def test_mlk_day_has_explicit_observed_session_boundary() -> None:
    policy = DerivXauUsdM15CoveragePolicy()
    rule = policy.holiday_rule(_dt("2026-01-19T12:00:00Z"))
    assert rule is not None
    assert rule.name == "Martin Luther King Jr. Day"
    assert policy.is_candle_expected(_dt("2026-01-19T16:30:00Z"))
    assert not policy.is_candle_expected(_dt("2026-01-19T16:45:00Z"))
    assert not policy.is_candle_expected(_dt("2026-01-19T23:45:00Z"))
    assert rule.holiday_date_source == "CME_OFFICIAL_HOLIDAY_SCHEDULE"
    assert rule.provider_boundary_source == "DERIV_PUBLIC_XAUUSD_OBSERVED_SESSION_BOUNDARY"


def test_presidents_day_has_explicit_policy() -> None:
    policy = DerivXauUsdM15CoveragePolicy()
    rule = policy.holiday_rule(_dt("2026-02-16T12:00:00Z"))
    assert rule is not None
    assert rule.name == "Presidents Day"
    assert policy.is_candle_expected(_dt("2026-02-16T16:30:00Z"))
    assert not policy.is_candle_expected(_dt("2026-02-16T16:45:00Z"))


def test_monday_weekly_open_is_expected() -> None:
    policy = DerivXauUsdM15CoveragePolicy()
    assert policy.is_candle_expected(_dt("2026-01-26T00:00:00Z"))
    assert policy.is_candle_expected(_dt("2026-01-26T04:45:00Z"))
    assert policy.is_candle_expected(_dt("2026-01-26T05:00:00Z"))


def test_thanksgiving_and_day_after_have_explicit_policies() -> None:
    policy = DerivXauUsdM15CoveragePolicy()
    thanksgiving = policy.holiday_rule(_dt("2025-11-27T12:00:00Z"))
    friday = policy.holiday_rule(_dt("2025-11-28T12:00:00Z"))
    assert thanksgiving is not None and thanksgiving.name == "Thanksgiving Day"
    assert friday is not None and friday.name == "Day After Thanksgiving"
    assert policy.is_candle_expected(_dt("2025-11-27T16:30:00Z"))
    assert not policy.is_candle_expected(_dt("2025-11-27T16:45:00Z"))
    assert policy.is_candle_expected(_dt("2025-11-28T20:45:00Z"))
    assert not policy.is_candle_expected(_dt("2025-11-28T21:00:00Z"))


def test_holiday_expected_open_gap_still_fails_closed() -> None:
    start, end = _dt("2026-01-19T16:15:00Z"), _dt("2026-01-19T17:00:00Z")
    candles = _fixture(start, end)
    assert _validate(candles, start, end).is_complete
    missing = [c for c in candles if c.time != _dt("2026-01-19T16:30:00Z")]
    assert _validate(missing, start, end).missing_count == 1


def test_unexpected_returned_candle_does_not_hide_missing_expected_bucket() -> None:
    start, end = _dt("2026-01-19T16:30:00Z"), _dt("2026-01-19T17:00:00Z")
    candles = _fixture(start, end)
    candles = [c for c in candles if c.time != _dt("2026-01-19T16:30:00Z")]
    unexpected = Candle(time=_dt("2026-01-19T16:45:00Z"), open=2600, high=2601,
                        low=2599, close=2600.2, source="deriv")
    result = _validate(candles + [unexpected], start, end)
    assert result.missing_count == 1
    assert result.unexpected_returned_count == 1
    assert result.expected_intersection_returned == result.expected_count - 1


def test_set_accounting_is_consistent() -> None:
    start, end = _dt("2026-01-19T00:00:00Z"), _dt("2026-01-19T23:45:00Z")
    candles = _fixture(start, end)
    unexpected = Candle(time=_dt("2026-01-19T23:45:00Z"), open=2600, high=2601,
                        low=2599, close=2600.2, source="deriv")
    result = _validate(candles + [unexpected], start, end)
    assert result.expected_count == 67
    assert result.returned_count == 68
    assert result.expected_intersection_returned == 67
    assert result.missing_count == 0
    assert result.unexpected_returned_count == 1
    assert result.expected_intersection_returned + result.unexpected_returned_count == result.returned_count


def test_unsupported_policy_fails_closed() -> None:
    with pytest.raises(MarketDataError, match="Unsupported historical coverage policy"):
        validate_historical_coverage(
            [], provider="deriv", canonical_symbol="R_100",
            provider_symbol="R_100", timeframe=Timeframe.M15,
            start=_dt("2026-08-24T10:00:00Z"), end=_dt("2026-08-24T10:15:00Z"),
        )


# ---------------------------------------------------------------------------
# DST-aware session tests
# ---------------------------------------------------------------------------

class TestSummerDSTClosure:
    """Summer (EDT = UTC-4): daily break is 21:00–22:00 UTC."""

    def test_last_open_candle_before_break(self) -> None:
        # 2026-08-24 is a Monday; 20:45 UTC = 16:45 EDT — last open bar
        policy = DerivXauUsdM15CoveragePolicy()
        assert policy.is_candle_expected(_dt("2026-08-24T20:45:00Z"))

    def test_first_closed_candle(self) -> None:
        # 21:00 UTC = 17:00 EDT — break starts
        policy = DerivXauUsdM15CoveragePolicy()
        assert not policy.is_candle_expected(_dt("2026-08-24T21:00:00Z"))

    def test_mid_break(self) -> None:
        policy = DerivXauUsdM15CoveragePolicy()
        assert not policy.is_candle_expected(_dt("2026-08-24T21:15:00Z"))
        assert not policy.is_candle_expected(_dt("2026-08-24T21:30:00Z"))
        assert not policy.is_candle_expected(_dt("2026-08-24T21:45:00Z"))

    def test_first_open_candle_after_break(self) -> None:
        # 22:00 UTC = 18:00 EDT — break ends
        policy = DerivXauUsdM15CoveragePolicy()
        assert policy.is_candle_expected(_dt("2026-08-24T22:00:00Z"))
        assert policy.is_candle_expected(_dt("2026-08-24T22:15:00Z"))

    def test_friday_close_boundary_summer(self) -> None:
        # 2026-08-28 is a Friday; 20:45 UTC = 16:45 EDT — last bar
        policy = DerivXauUsdM15CoveragePolicy()
        assert policy.is_candle_expected(_dt("2026-08-28T20:45:00Z"))
        assert not policy.is_candle_expected(_dt("2026-08-28T21:00:00Z"))


class TestWinterDSTClosure:
    """Winter (EST = UTC-5): daily break is 22:00–23:00 UTC."""

    def test_last_open_candle_before_break(self) -> None:
        # 2026-01-26 is a Monday; 21:45 UTC = 16:45 EST — last open bar
        policy = DerivXauUsdM15CoveragePolicy()
        assert policy.is_candle_expected(_dt("2026-01-26T21:45:00Z"))

    def test_first_closed_candle(self) -> None:
        # 22:00 UTC = 17:00 EST — break starts
        policy = DerivXauUsdM15CoveragePolicy()
        assert not policy.is_candle_expected(_dt("2026-01-26T22:00:00Z"))

    def test_mid_break(self) -> None:
        policy = DerivXauUsdM15CoveragePolicy()
        assert not policy.is_candle_expected(_dt("2026-01-26T22:15:00Z"))
        assert not policy.is_candle_expected(_dt("2026-01-26T22:30:00Z"))
        assert not policy.is_candle_expected(_dt("2026-01-26T22:45:00Z"))

    def test_first_open_candle_after_break(self) -> None:
        # 23:00 UTC = 18:00 EST — break ends
        policy = DerivXauUsdM15CoveragePolicy()
        assert policy.is_candle_expected(_dt("2026-01-26T23:00:00Z"))
        assert policy.is_candle_expected(_dt("2026-01-26T23:15:00Z"))

    def test_friday_close_boundary_winter(self) -> None:
        # 2026-01-30 is a Friday.
        # Deriv public frxXAUUSD closes at 20:45 UTC on Fridays — DST-independent.
        # In winter (EST=UTC-5): 20:45 UTC = 15:45 EST (last open bar),
        # 21:00 UTC = 16:00 EST (already closed by the 20:45 UTC cutoff).
        policy = DerivXauUsdM15CoveragePolicy()
        assert policy.is_candle_expected(_dt("2026-01-30T20:45:00Z"))   # last bar
        assert not policy.is_candle_expected(_dt("2026-01-30T21:00:00Z"))  # closed
        assert not policy.is_candle_expected(_dt("2026-01-30T21:45:00Z"))  # still closed


class TestDSTTransitionBoundaries:
    """Candles immediately surrounding US DST transitions.

    Spring-forward: 2026-03-08 — clocks spring forward at 02:00 AM EST→EDT.
    Fall-back:      2025-11-02 — clocks fall back at 02:00 AM EDT→EST.
    """

    # ---- Spring forward (2026-03-08, Sunday) --------------------------------
    # The Sunday of DST changeover is a full market-closed day; Monday picks up
    # the new summer schedule (break = 21:00–22:00 UTC).

    def test_spring_forward_monday_summer_schedule(self) -> None:
        # 2026-03-09 Monday — first trading day after spring-forward
        policy = DerivXauUsdM15CoveragePolicy()
        # 20:45 UTC = 16:45 EDT — expected open
        assert policy.is_candle_expected(_dt("2026-03-09T20:45:00Z"))
        # 21:00 UTC = 17:00 EDT — break start
        assert not policy.is_candle_expected(_dt("2026-03-09T21:00:00Z"))
        # 22:00 UTC = 18:00 EDT — break end
        assert policy.is_candle_expected(_dt("2026-03-09T22:00:00Z"))

    def test_spring_forward_sunday_closed(self) -> None:
        policy = DerivXauUsdM15CoveragePolicy()
        assert not policy.is_candle_expected(_dt("2026-03-08T12:00:00Z"))

    # ---- Fall back (2025-11-02, Sunday) -------------------------------------
    # Sunday is closed; the following Monday adopts the winter schedule
    # (break = 22:00–23:00 UTC).

    def test_fall_back_monday_winter_schedule(self) -> None:
        # 2025-11-03 Monday — first trading day after fall-back
        policy = DerivXauUsdM15CoveragePolicy()
        # 21:45 UTC = 16:45 EST — expected open
        assert policy.is_candle_expected(_dt("2025-11-03T21:45:00Z"))
        # 22:00 UTC = 17:00 EST — break start
        assert not policy.is_candle_expected(_dt("2025-11-03T22:00:00Z"))
        # 23:00 UTC = 18:00 EST — break end
        assert policy.is_candle_expected(_dt("2025-11-03T23:00:00Z"))

    def test_fall_back_friday_before_transition(self) -> None:
        # 2025-10-31 Friday — still summer (EDT); break at 21:00 UTC
        policy = DerivXauUsdM15CoveragePolicy()
        # 20:45 UTC = 16:45 EDT — last bar
        assert policy.is_candle_expected(_dt("2025-10-31T20:45:00Z"))
        assert not policy.is_candle_expected(_dt("2025-10-31T21:00:00Z"))


class TestCompleteCoverageValidationDST:
    """validate_historical_coverage round-trip sanity for DST seasons."""

    def test_summer_week_complete_coverage(self) -> None:
        start, end = _dt("2026-08-24T00:00:00Z"), _dt("2026-08-24T23:45:00Z")
        candles = _fixture(start, end)
        result = _validate(candles, start, end)
        assert result.is_complete
        # The provider's Monday weekly open is 00:00 UTC; only the 4-slot break is closed.
        assert result.legitimate_closed_count == 4

    def test_winter_week_complete_coverage(self) -> None:
        start, end = _dt("2026-01-26T00:00:00Z"), _dt("2026-01-26T23:45:00Z")
        candles = _fixture(start, end)
        result = _validate(candles, start, end)
        assert result.is_complete
        # The provider's Monday weekly open is 00:00 UTC; only the 4-slot break is closed.
        assert result.legitimate_closed_count == 4

    def test_missing_summer_candle_detected(self) -> None:
        start, end = _dt("2026-08-24T20:30:00Z"), _dt("2026-08-24T22:15:00Z")
        candles = _fixture(start, end)
        # Remove the 20:30 candle
        missing = [c for c in candles if c.time != _dt("2026-08-24T20:30:00Z")]
        result = _validate(missing, start, end)
        assert result.missing_count == 1
        assert result.first_missing == _dt("2026-08-24T20:30:00Z")

    def test_missing_winter_candle_detected(self) -> None:
        start, end = _dt("2026-01-26T21:30:00Z"), _dt("2026-01-26T23:15:00Z")
        candles = _fixture(start, end)
        # Remove the 21:30 candle
        missing = [c for c in candles if c.time != _dt("2026-01-26T21:30:00Z")]
        result = _validate(missing, start, end)
        assert result.missing_count == 1
        assert result.first_missing == _dt("2026-01-26T21:30:00Z")


@pytest.mark.asyncio
async def test_cached_only_uses_no_transport_and_active_gap_fails(tmp_path, monkeypatch) -> None:
    start, end = _dt("2026-08-24T00:00:00Z"), _dt("2026-08-26T12:00:00Z")
    store = CandleStore(tmp_path / "cached.sqlite3")
    candles = _fixture(start, end)
    store.save_candles("XAUUSD", Timeframe.M15, candles, provider="deriv")

    class ForbiddenTransport:
        def __init__(self, *args, **kwargs):
            raise AssertionError("cached-only must not construct public transport")

    monkeypatch.setattr(research_cli, "DerivPublicMarketData", ForbiddenTransport)
    args = Namespace(symbol="XAUUSD", timeframe="M15", start=start.isoformat(),
                     end=end.isoformat(), initial_capital=10000.0,
                     cache=store.db_path, cached_only=True, fetch_missing=False)
    assert await research_cli._run(args) == 0

    gap_time = _dt("2026-08-25T10:30:00Z")
    with store._connect() as connection:
        connection.execute(
            "DELETE FROM candles WHERE provider=? AND symbol=? AND timeframe=? AND time=?",
            ("deriv", "XAUUSD", "M15", int(gap_time.timestamp())),
        )
        connection.commit()
    with pytest.raises(MarketDataError, match="not complete in cache"):
        await research_cli._run(args)
