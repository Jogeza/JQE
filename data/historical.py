"""Historical candle data service: download, cache, detect gaps, fill them.

.. important::
    This milestone's brief described this module as an "MT5 history
    download." Per the platform's broker-agnostic architecture
    established in the Broker Foundation milestone (the Quant Core
    must never import a broker SDK directly — see
    docs/architecture.md, "Broker layer"), it's implemented against
    :class:`broker.base.BrokerGateway` instead, so it works
    identically with any configured broker (MT5, Deriv, Simulation),
    not just MT5. A caller who specifically wants MT5 gets it by
    passing an ``MT5Gateway`` instance — nothing here hardcodes a
    broker choice.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from broker.base import BrokerGateway
from broker.types import TIMEFRAME_SECONDS, Candle, Timeframe
from core.exceptions import MarketDataError
from core.logger import logger
from data.storage import CandleStore, find_gaps
from data.types import SyncReport

#: A cache is considered "already current" if its latest candle is
#: within this many candle-widths of now — avoids an unnecessary
#: network round trip for a one-candle-width discrepancy that's likely
#: just "the current candle hasn't closed yet".
_FRESHNESS_TOLERANCE_CANDLES = 1


class HistoricalDataService:
    """Serves historical candles from cache, downloading only what's missing.

    Attributes:
        gateway: The (already-connected) :class:`~broker.base.
            BrokerGateway` used to download candles not already cached.
        store: The :class:`~data.storage.CandleStore` used for local
            persistence.
    """

    def __init__(self, gateway: BrokerGateway, store: CandleStore | None = None) -> None:
        self.gateway = gateway
        self.store = store or CandleStore()

    async def get_candles(
        self, symbol: str, timeframe: Timeframe, count: int, fill_gaps: bool = True
    ) -> list[Candle]:
        """Returns the most recent ``count`` candles, using cache + incremental download.

        This is "automatic loading": callers don't manage cache vs.
        download themselves — the cache is checked, only the missing
        portion (if any) is downloaded and persisted, and (unless
        disabled) any gaps found in the cached history are filled,
        before returning.

        Args:
            symbol: Instrument symbol.
            timeframe: Candle timeframe.
            count: Number of most-recent candles to return.
            fill_gaps: Whether to detect and fill gaps in cached
                history before returning. Disable for a faster call
                when gap-free data isn't required (e.g. a quick
                approximate check).

        Returns:
            Up to ``count`` candles, oldest to newest. Shorter than
            ``count`` only if the broker itself has less history
            available.

        Raises:
            core.exceptions.MarketDataError: If a download is needed
                and fails.
            core.exceptions.CacheError: If the local cache is
                unreadable/unwritable.
        """
        await self._sync_recent(symbol, timeframe, count)
        if fill_gaps:
            await self.fill_gaps(symbol, timeframe)
        return self.store.load_latest(symbol, timeframe, count)

    async def sync(self, symbol: str, timeframe: Timeframe, count: int) -> SyncReport:
        """Ensures the cache holds ``count`` recent, gap-free candles and reports the result.

        The main explicit entry point for a scheduled/background sync
        job — combines incremental recent-data download, gap filling,
        and cache validation into one call and one report, rather than
        requiring the caller to orchestrate
        :meth:`get_candles`/:meth:`fill_gaps`/``store.validate``
        separately.

        Args:
            symbol: Instrument symbol.
            timeframe: Candle timeframe.
            count: Minimum number of recent candles the cache should hold.

        Returns:
            A report of what was downloaded/filled and the resulting
            cache's validation status.
        """
        downloaded_recent = await self._sync_recent(symbol, timeframe, count)
        gaps_filled, downloaded_gaps = await self.fill_gaps(symbol, timeframe, return_count=True)
        validation = self.store.validate(symbol, timeframe)

        report = SyncReport(
            symbol=symbol,
            timeframe=timeframe.value,
            candles_downloaded=downloaded_recent + downloaded_gaps,
            gaps_filled=gaps_filled,
            candle_count=validation.candle_count,
            is_valid=validation.is_valid,
            issues=validation.issues,
        )
        logger.info("Sync complete for {} {}: {}", symbol, timeframe.value, report.model_dump())
        return report

    async def fill_gaps(
        self, symbol: str, timeframe: Timeframe, return_count: bool = False
    ) -> int | tuple[int, int]:
        """Detects gaps in cached history and downloads data to fill them.

        Args:
            symbol: Instrument symbol.
            timeframe: Candle timeframe.
            return_count: If ``True``, also return the number of
                candles downloaded while filling (used internally by
                :meth:`sync` for its report; most callers only need the
                gap count).

        Returns:
            Number of gaps successfully filled, or (if
            ``return_count``) a ``(gaps_filled, candles_downloaded)``
            tuple.
        """
        candles = self.store.load_candles(symbol, timeframe)
        step_seconds = TIMEFRAME_SECONDS[timeframe]

        if len(candles) < 2:
            return (0, 0) if return_count else 0

        gaps = find_gaps(candles, step_seconds)
        if not gaps:
            return (0, 0) if return_count else 0

        logger.warning(
            "Found {} gap(s) in cached {} {} data — filling", len(gaps), symbol, timeframe.value
        )

        filled = 0
        downloaded = 0
        for gap_start, gap_end in gaps:
            span_seconds = (gap_end - gap_start).total_seconds()
            # +2 candles of buffer so rounding never leaves the gap's
            # edges unfilled.
            candles_needed = max(1, int(span_seconds // step_seconds) + 2)
            try:
                fetched = await self.gateway.get_candles(
                    symbol, timeframe, candles_needed, end=gap_end
                )
            except MarketDataError:
                logger.error(
                    "Failed to fill gap {} -> {} for {} {}",
                    gap_start,
                    gap_end,
                    symbol,
                    timeframe.value,
                )
                continue

            # Defensive: only persist candles that actually fall within
            # the gap window, in case a gateway returns extra candles
            # around the requested edges.
            relevant = [c for c in fetched if gap_start < c.time < gap_end]
            if relevant:
                self.store.save_candles(symbol, timeframe, relevant)
                filled += 1
                downloaded += len(relevant)

        return (filled, downloaded) if return_count else filled

    async def _sync_recent(self, symbol: str, timeframe: Timeframe, count: int) -> int:
        """Ensures the cache has at least ``count`` of the most recent candles.

        Downloads only the gap between what's cached and now (an
        incremental update), not the full requested window — unless
        nothing is cached yet, in which case a full download is the
        only option.

        Returns:
            Number of candles downloaded.
        """
        coverage = self.store.get_coverage(symbol, timeframe)
        step = timedelta(seconds=TIMEFRAME_SECONDS[timeframe])
        now = datetime.now(timezone.utc)

        if coverage is None:
            logger.info(
                "No cached data for {} {} — downloading {} candle(s)",
                symbol,
                timeframe.value,
                count,
            )
            candles = await self.gateway.get_candles(symbol, timeframe, count)
            return self.store.save_candles(symbol, timeframe, candles)

        _, latest_cached = coverage
        staleness = now - latest_cached
        downloaded = 0

        if staleness > step * _FRESHNESS_TOLERANCE_CANDLES:
            candles_needed = int(staleness / step) + 1
            logger.info(
                "Cache for {} {} is {} behind — downloading {} incremental candle(s)",
                symbol,
                timeframe.value,
                staleness,
                candles_needed,
            )
            candles = await self.gateway.get_candles(symbol, timeframe, candles_needed)
            downloaded += self.store.save_candles(symbol, timeframe, candles)

        # The incremental fetch above only covers the recent edge — if
        # the cache is smaller than the requested `count` entirely
        # (e.g. a brand-new symbol with a small existing cache and a
        # much larger `count` request), top it up explicitly.
        if self.store.count(symbol, timeframe) < count:
            candles = await self.gateway.get_candles(symbol, timeframe, count)
            downloaded += self.store.save_candles(symbol, timeframe, candles)

        return downloaded
