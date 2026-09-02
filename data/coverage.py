"""Deterministic provider/session-aware historical coverage validation.

Storage deliberately has no market-hours knowledge.  This module is the one
authoritative place that decides which candle buckets a canonical cached
research range must contain.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Protocol, Sequence

from broker.types import TIMEFRAME_SECONDS, Candle, Timeframe
from core.exceptions import MarketDataError


class HistoricalCoveragePolicy(Protocol):
    """Provider/instrument policy for expected UTC candle timestamps."""

    def is_candle_expected(self, timestamp: datetime) -> bool: ...


@dataclass(frozen=True, slots=True)
class DerivXauUsdM15CoveragePolicy:
    """Deriv public ``frxXAUUSD`` M15 session policy.

    The unauthenticated ``frxXAUUSD`` public-history service was verified on
    the fixed 2026-08-24..2026-08-31 range: M15 buckets stop at 20:45 and
    resume at 22:00 Monday-Thursday, while the weekend runs from after Friday
    20:45 through Monday 00:00.  Thus closed bucket semantics are
    [21:00, 22:00) Monday-Thursday plus that complete weekend interval.

    Deriv documents the unauthenticated schedule API and its open/close,
    trading-day, and event fields at
    https://developers.deriv.com/docs/system/trading-times/ .
    """

    def is_candle_expected(self, timestamp: datetime) -> bool:
        timestamp = _require_utc(timestamp)
        weekday = timestamp.weekday()
        bucket_time = timestamp.time().replace(tzinfo=None)
        if weekday == 5:  # Saturday
            return False
        if weekday == 6:  # Sunday is closed for public frxXAUUSD history.
            return False
        if weekday == 4:  # Friday close: the 20:45 bucket is the last one.
            return bucket_time <= time(20, 45)
        return bucket_time < time(21, 0) or bucket_time >= time(22, 0)


@dataclass(frozen=True, slots=True)
class CoverageValidationResult:
    expected_count: int
    missing_count: int
    first_missing: datetime | None
    legitimate_closed_count: int

    @property
    def is_complete(self) -> bool:
        return self.missing_count == 0


def get_coverage_policy(
    provider: str, canonical_symbol: str, provider_symbol: str, timeframe: Timeframe
) -> HistoricalCoveragePolicy:
    identity = (
        provider.strip().lower(), canonical_symbol.strip().upper(),
        provider_symbol.strip(), timeframe,
    )
    if identity == ("deriv", "XAUUSD", "frxXAUUSD", Timeframe.M15):
        return DerivXauUsdM15CoveragePolicy()
    raise MarketDataError(
        "Unsupported historical coverage policy",
        provider=provider, symbol=canonical_symbol,
        provider_symbol=provider_symbol, timeframe=timeframe.value,
    )


def validate_historical_coverage(
    candles: Sequence[Candle], *, provider: str, canonical_symbol: str,
    provider_symbol: str, timeframe: Timeframe, start: datetime, end: datetime,
) -> CoverageValidationResult:
    """Validate every expected, aligned UTC bucket in an inclusive range."""
    start, end = _require_utc(start), _require_utc(end)
    if end < start:
        raise MarketDataError("Historical coverage range is not ordered")
    policy = get_coverage_policy(provider, canonical_symbol, provider_symbol, timeframe)
    step = timedelta(seconds=TIMEFRAME_SECONDS[timeframe])
    if int(start.timestamp()) % int(step.total_seconds()) or int(end.timestamp()) % int(step.total_seconds()):
        raise MarketDataError("Historical coverage bounds must align to the timeframe")
    present = {candle.time.astimezone(timezone.utc) for candle in candles}
    expected = closed = missing = 0
    first_missing = None
    current = start
    while current <= end:
        if policy.is_candle_expected(current):
            expected += 1
            if current not in present:
                missing += 1
                first_missing = first_missing or current
        else:
            closed += 1
        current += step
    return CoverageValidationResult(expected, missing, first_missing, closed)


def require_complete_historical_coverage(**kwargs) -> CoverageValidationResult:
    result = validate_historical_coverage(**kwargs)
    if not result.is_complete:
        raise MarketDataError(
            "Requested range is not complete in cache",
            provider=kwargs["provider"], symbol=kwargs["canonical_symbol"],
            timeframe=kwargs["timeframe"].value,
            first_missing=result.first_missing.isoformat() if result.first_missing else None,
            missing_count=result.missing_count,
        )
    return result


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise MarketDataError("Historical coverage timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)
