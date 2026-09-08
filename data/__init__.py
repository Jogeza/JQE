"""The data layer: local historical-candle caching, gap detection, and
broker-agnostic incremental download.

    >>> from broker import get_gateway
    >>> from data import HistoricalDataService
    >>> service = HistoricalDataService(get_gateway())
    >>> candles = await service.get_candles("R_100", Timeframe.M5, 500)

See docs/architecture.md, "Data layer", for the caching/gap-filling
design.
"""

from data.historical import HistoricalDataService
from data.market_observation import closed_observations_from_candles, resolved_market_source
from data.storage import CandleStore, find_gaps
from data.types import CacheValidationResult, SyncReport

__all__ = [
    "CacheValidationResult",
    "CandleStore",
    "HistoricalDataService",
    "closed_observations_from_candles",
    "resolved_market_source",
    "SyncReport",
    "find_gaps",
]
