"""DTOs shared by the data layer (:mod:`data.storage`, :mod:`data.historical`)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class CacheValidationResult(BaseModel):
    """Result of validating a symbol/timeframe's cached candle data.

    Attributes:
        is_valid: ``True`` if no issues were found.
        issues: Human-readable descriptions of every problem found
            (non-monotonic timestamps, invalid OHLC values, detected
            gaps, ...). Empty when ``is_valid`` is ``True``.
        candle_count: Number of candles examined.
    """

    is_valid: bool
    issues: list[str] = Field(default_factory=list)
    candle_count: int


class SyncReport(BaseModel):
    """Result of :meth:`data.historical.HistoricalDataService.sync`.

    Attributes:
        symbol: Instrument symbol synced.
        timeframe: Timeframe synced, as its string value (e.g. ``"M5"``).
        candles_downloaded: Total candles fetched from the broker
            during this sync (incremental update + gap fill combined).
        gaps_filled: Number of distinct gaps successfully filled.
        candle_count: Total candles now in the cache for this
            symbol/timeframe after syncing.
        is_valid: Whether the cache passed validation after syncing.
        issues: Validation issues found, if any (should be empty when
            ``is_valid`` is ``True``).
    """

    symbol: str
    timeframe: str
    candles_downloaded: int
    gaps_filled: int
    candle_count: int
    is_valid: bool
    issues: list[str] = Field(default_factory=list)
