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


def test_unsupported_policy_fails_closed() -> None:
    with pytest.raises(MarketDataError, match="Unsupported historical coverage policy"):
        validate_historical_coverage(
            [], provider="deriv", canonical_symbol="R_100",
            provider_symbol="R_100", timeframe=Timeframe.M15,
            start=_dt("2026-08-24T10:00:00Z"), end=_dt("2026-08-24T10:15:00Z"),
        )


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
