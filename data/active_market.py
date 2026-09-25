"""Canonical active-market identity and closed-candle freshness semantics."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from broker.types import Candle, TIMEFRAME_SECONDS, Timeframe


class ActiveMarketContext(BaseModel):
    canonical_symbol: str
    provider_symbol: str
    display_name: str
    selected_timeframe: str
    timeframe_seconds: int
    latest_stored_candle_close: datetime | None = None
    expected_latest_closed_candle: datetime
    market_data_observation_time: datetime
    strategy_evaluation_time: datetime
    setup_creation_time: datetime
    setup_expiry_time: datetime
    data_source: Literal["SIMULATION", "DERIV_PUBLIC", "BROKER", "UNAVAILABLE"]
    cache_status: Literal["REFRESHED", "FRESH_CACHE", "CACHE_ONLY", "EMPTY"]
    synchronization_state: Literal["SYNCHRONIZED", "STALE", "FORMING", "UNKNOWN"]
    reason_codes: list[str] = Field(default_factory=list)
    latest_closed_candle_at: datetime | None = None
    expected_closed_candle_at: datetime
    freshness_age_seconds: Decimal | None = None
    freshness_tolerance_seconds: int
    freshness_state: Literal["FRESH", "STALE", "FORMING", "UNKNOWN"]
    freshness_reason_codes: list[str] = Field(default_factory=list)
    schema_version: int = 1


def is_continuous_market(symbol: str) -> bool:
    normalized = symbol.strip().upper()
    return normalized.startswith(("R_", "1HZ", "BTC", "ETH", "SOL", "CRY"))


def symbol_display_name(symbol: str) -> str:
    normalized = symbol.strip().upper()
    names = {
        "R_75": "Volatility 75 Index",
        "XAUUSD": "Gold / US Dollar",
        "EURUSD": "Euro / US Dollar",
        "GBPUSD": "British Pound / US Dollar",
        "USDJPY": "US Dollar / Japanese Yen",
        "BTCUSD": "Bitcoin / US Dollar",
    }
    return names.get(normalized, normalized)


def expected_latest_closed_candle_at(
    observed_at: datetime,
    timeframe: Timeframe,
    symbol: str,
    *,
    continuous_market: bool | None = None,
) -> datetime:
    """Return the latest expected UTC close, respecting the FX weekend closure."""
    now = observed_at.astimezone(timezone.utc)
    step = TIMEFRAME_SECONDS[timeframe]
    epoch = int(now.timestamp())
    candidate = datetime.fromtimestamp(epoch - epoch % step, tz=timezone.utc)
    if continuous_market is True or (
        continuous_market is None and is_continuous_market(symbol)
    ):
        return candidate
    weekday = candidate.weekday()
    if weekday == 5:  # Saturday -> Friday 22:00 UTC
        return (candidate - timedelta(days=1)).replace(hour=22, minute=0, second=0, microsecond=0)
    if weekday == 6 and candidate.hour < 22:  # Sunday before FX reopen
        return (candidate - timedelta(days=2)).replace(hour=22, minute=0, second=0, microsecond=0)
    if weekday == 4 and candidate.hour > 22:
        return candidate.replace(hour=22, minute=0, second=0, microsecond=0)
    return candidate


def fully_closed_candles(
    candles: list[Candle], timeframe: Timeframe, observed_at: datetime
) -> list[Candle]:
    step = timedelta(seconds=TIMEFRAME_SECONDS[timeframe])
    now = observed_at.astimezone(timezone.utc)
    return [
        candle for candle in candles
        if candle.time.astimezone(timezone.utc) + step <= now
    ]


def candle_close_time(candle: Candle, timeframe: Timeframe) -> datetime:
    return candle.time.astimezone(timezone.utc) + timedelta(
        seconds=TIMEFRAME_SECONDS[timeframe]
    )


def freshness_facts(
    candles: list[Candle], *, symbol: str, timeframe: Timeframe,
    observed_at: datetime, cache_only: bool,
    continuous_market: bool | None = None,
) -> tuple[datetime | None, datetime, Decimal | None, str, list[str]]:
    expected = expected_latest_closed_candle_at(
        observed_at,
        timeframe,
        symbol,
        continuous_market=continuous_market,
    )
    closed = fully_closed_candles(candles, timeframe, observed_at)
    if not closed:
        return None, expected, None, "UNKNOWN", ["NO_FULLY_CLOSED_CANDLE"]
    latest = candle_close_time(closed[-1], timeframe)
    tolerance = TIMEFRAME_SECONDS[timeframe]
    delta = Decimal(str((expected - latest).total_seconds()))
    if delta < -Decimal(tolerance):
        return latest, expected, abs(delta), "UNKNOWN", ["MARKET_CLOCK_AHEAD"]
    age = max(Decimal("0"), delta)
    reasons: list[str] = []
    if cache_only:
        reasons.append("CACHE_ONLY")
    if age > Decimal(tolerance):
        reasons.append("LATEST_CLOSED_CANDLE_LATE")
        return latest, expected, age, "STALE", reasons
    reasons.append("LATEST_CLOSED_CANDLE_WITHIN_TOLERANCE")
    return latest, expected, age, "FRESH", reasons
