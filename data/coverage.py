"""Deterministic provider/session-aware historical coverage validation.

Storage deliberately has no market-hours knowledge.  This module is the one
authoritative place that decides which candle buckets a canonical cached
research range must contain.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Protocol, Sequence
from zoneinfo import ZoneInfo

from broker.types import TIMEFRAME_SECONDS, Candle, Timeframe
from core.exceptions import MarketDataError


class HistoricalCoveragePolicy(Protocol):
    """Provider/instrument policy for expected UTC candle timestamps."""

    def is_candle_expected(self, timestamp: datetime) -> bool: ...


@dataclass(frozen=True, slots=True)
class HolidaySessionRule:
    name: str
    date: date
    expected_intervals: tuple[tuple[time, time], ...]
    closed_intervals: tuple[tuple[time, time], ...]
    holiday_date_source: str
    provider_boundary_source: str

    @property
    def source(self) -> str:
        return f"{self.holiday_date_source}; {self.provider_boundary_source}"


@dataclass(frozen=True, slots=True)
class DerivXauUsdM15CoveragePolicy:
    """Deriv public ``frxXAUUSD`` M15 session policy.

    Session boundaries as observed on Deriv public candle history:

    **Weekday daily break (Mon–Thu)**: Always 5:00–6:00 PM New York time
    (``America/New_York``), resolved via ``zoneinfo`` for DST:

    * Summer (EDT, UTC-4): 21:00–22:00 UTC.
    * Winter (EST, UTC-5): 22:00–23:00 UTC.

    **Friday close**: Always **20:45 UTC** — DST-independent.  This was
    confirmed by probing both summer (20:45 UTC = 16:45 EDT) and winter
    (20:45 UTC = 15:45 EST) sessions; the provider stops at the same UTC
    timestamp both seasons.

    **Weekend**: Saturday and Sunday in UTC are closed.

    Known CME metals holiday dates are handled explicitly. CME materials
    establish the holiday dates, but not Deriv-specific intraday boundaries;
    those boundaries are recorded separately as observed public-provider
    behavior.
    """

    holiday_rules = {
        date(2026, 1, 19): HolidaySessionRule(
            "Martin Luther King Jr. Day", date(2026, 1, 19),
            ((time(0, 0), time(16, 45)),),
            ((time(16, 45), time(23, 59, 59)),),
            "CME_OFFICIAL_HOLIDAY_SCHEDULE",
            "DERIV_PUBLIC_XAUUSD_OBSERVED_SESSION_BOUNDARY",
        ),
        date(2026, 2, 16): HolidaySessionRule(
            "Presidents Day", date(2026, 2, 16),
            ((time(0, 0), time(16, 45)),),
            ((time(16, 45), time(23, 59, 59)),),
            "CME_OFFICIAL_HOLIDAY_SCHEDULE",
            "DERIV_PUBLIC_XAUUSD_OBSERVED_SESSION_BOUNDARY",
        ),
        date(2025, 11, 27): HolidaySessionRule(
            "Thanksgiving Day", date(2025, 11, 27),
            ((time(0, 0), time(16, 45)),),
            ((time(16, 45), time(23, 59, 59)),),
            "CME_OFFICIAL_HOLIDAY_SCHEDULE",
            "DERIV_PUBLIC_XAUUSD_OBSERVED_SESSION_BOUNDARY",
        ),
        date(2025, 11, 28): HolidaySessionRule(
            "Day After Thanksgiving", date(2025, 11, 28),
            ((time(0, 0), time(21, 0)),),
            ((time(21, 0), time(23, 59, 59)),),
            "CME_OFFICIAL_HOLIDAY_SCHEDULE",
            "DERIV_PUBLIC_XAUUSD_OBSERVED_SESSION_BOUNDARY",
        ),
    }

    def holiday_rule(self, timestamp: datetime) -> HolidaySessionRule | None:
        return self.holiday_rules.get(_require_utc(timestamp).date())

    def is_candle_expected(self, timestamp: datetime) -> bool:
        timestamp = _require_utc(timestamp)
        holiday = self.holiday_rule(timestamp)
        if holiday is not None:
            bucket_time = timestamp.time().replace(tzinfo=None)
            return any(start <= bucket_time < end for start, end in holiday.expected_intervals)
        # ------------------------------------------------------------------ #
        # Explicit CME metals early-close dates (UTC date → last expected      #
        # bucket time in UTC, observed on Deriv public frxXAUUSD history).    #
        # Unknown holidays remain fail-closed.                                 #
        # ------------------------------------------------------------------ #
        early_closes = {
            datetime(2026, 6, 19, tzinfo=timezone.utc).date(),
            datetime(2026, 7, 3, tzinfo=timezone.utc).date(),
            datetime(2026, 9, 7, tzinfo=timezone.utc).date(),
        }
        if timestamp.date() in early_closes:
            return timestamp.time().replace(tzinfo=None) <= time(17, 0)
        # ------------------------------------------------------------------ #
        # Friday close is always 20:45 UTC (DST-independent).                 #
        # Weekday breaks (Mon–Thu) are 17:00–18:00 New York time (DST-aware). #
        # ------------------------------------------------------------------ #
        utc_time = timestamp.time().replace(tzinfo=None)
        # Deriv's public XAUUSD week opens Monday at 00:00 UTC. This is a
        # provider session boundary, not a holiday exception.
        if timestamp.weekday() == 0 and utc_time < time(5, 0):
            return True
        ny_dt = timestamp.astimezone(ZoneInfo("America/New_York"))
        ny_weekday = ny_dt.weekday()
        if ny_weekday == 5:  # Saturday in New York
            return False
        if ny_weekday == 6:  # Sunday in New York
            return False
        if ny_weekday == 4:  # Friday: always closes at 20:45 UTC
            # The cutoff is anchored to the Friday UTC date.  Early Saturday
            # UTC is still Friday evening in New York, but remains closed.
            return timestamp.weekday() == 4 and utc_time <= time(20, 45)
        # Monday–Thursday: daily break is 17:00–18:00 New York time (DST-aware)
        ny_time = ny_dt.time().replace(tzinfo=None)
        return ny_time < time(17, 0) or ny_time >= time(18, 0)


@dataclass(frozen=True, slots=True)
class CoverageValidationResult:
    expected_count: int
    missing_count: int
    first_missing: datetime | None
    legitimate_closed_count: int
    returned_count: int = 0
    expected_intersection_returned: int = 0
    unexpected_returned_count: int = 0
    missing_expected_buckets: tuple[datetime, ...] = ()
    unexpected_returned_buckets: tuple[datetime, ...] = ()

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
    expected_buckets: set[datetime] = set()
    closed = 0
    current = start
    while current <= end:
        if policy.is_candle_expected(current):
            expected_buckets.add(current)
        else:
            closed += 1
        current += step
    missing_buckets = tuple(sorted(expected_buckets - present))
    unexpected_buckets = tuple(sorted(present - expected_buckets))
    return CoverageValidationResult(
        expected_count=len(expected_buckets),
        missing_count=len(missing_buckets),
        first_missing=missing_buckets[0] if missing_buckets else None,
        legitimate_closed_count=closed,
        returned_count=len(present),
        expected_intersection_returned=len(expected_buckets & present),
        unexpected_returned_count=len(unexpected_buckets),
        missing_expected_buckets=missing_buckets,
        unexpected_returned_buckets=unexpected_buckets,
    )


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
