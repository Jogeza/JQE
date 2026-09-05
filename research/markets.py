"""Backend-owned public research market catalogue."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Awaitable, Callable, Sequence

from broker.types import TIMEFRAME_SECONDS, Timeframe
from core.exceptions import MarketDataError

DERIV_PROVIDER = "deriv"
DERIV_TIMEFRAMES = tuple(tf for tf in Timeframe if TIMEFRAME_SECONDS[tf] in {
    60, 300, 900, 1800, 3600, 14400, 86400
})


class HistoricalCapability(str, Enum):
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class MarketInstrument:
    provider: str
    provider_symbol: str
    canonical_symbol: str
    display_name: str
    market: str
    market_display_name: str | None
    subgroup: str
    submarket: str
    submarket_display_name: str | None
    instrument_type: str
    pip_size: float
    exchange_is_open: bool
    is_trading_suspended: bool
    historical_data_supported: HistoricalCapability = HistoricalCapability.UNKNOWN
    timeframes: tuple[Timeframe, ...] = DERIV_TIMEFRAMES


@dataclass(frozen=True, slots=True)
class MarketCatalogue:
    provider: str
    fetched_at: datetime | None
    instruments: tuple[MarketInstrument, ...]
    source_status: str
    cache_status: str
    error: str | None = None


def _text(raw: dict[str, Any], current: str, legacy: str | None = None, *, required: bool = True) -> str:
    value = raw.get(current, raw.get(legacy) if legacy else None)
    if not isinstance(value, str) or not value.strip():
        if required: raise ValueError(current)
        return ""
    return value.strip()


def adapt_active_symbols(payload: dict[str, Any]) -> tuple[MarketInstrument, ...]:
    """Normalize current schema and deliberate legacy SmartCharts fields."""
    entries = payload.get("active_symbols")
    if not isinstance(entries, list):
        raise MarketDataError("Malformed Deriv active_symbols response")
    result: list[MarketInstrument] = []
    for raw in entries:
        if not isinstance(raw, dict): continue
        try:
            provider_symbol = _text(raw, "underlying_symbol", "symbol")
            display_name = _text(raw, "underlying_symbol_name", "display_name")
            instrument_type = _text(raw, "underlying_symbol_type", "symbol_type")
            market = _text(raw, "market")
            subgroup = _text(raw, "subgroup", required=False) or "unknown"
            submarket = _text(raw, "submarket")
            pip = raw.get("pip_size", raw.get("pip"))
            if isinstance(pip, bool) or not isinstance(pip, (int, float)) or pip <= 0: raise ValueError("pip_size")
            opened, suspended = raw.get("exchange_is_open"), raw.get("is_trading_suspended")
            if opened not in (0, 1) or suspended not in (0, 1): raise ValueError("state")
        except ValueError:
            continue
        canonical = provider_symbol[3:] if provider_symbol.startswith("frx") and len(provider_symbol) > 3 else provider_symbol
        result.append(MarketInstrument(DERIV_PROVIDER, provider_symbol, canonical, display_name,
            market, _text(raw, "market_display_name", required=False) or None, subgroup, submarket,
            _text(raw, "submarket_display_name", required=False) or None, instrument_type,
            float(pip), bool(opened), bool(suspended)))
    result.sort(key=lambda item: (item.market, item.submarket, item.display_name.casefold(), item.provider_symbol))
    return tuple(result)


class MarketCatalogueService:
    def __init__(self, loader: Callable[[], Awaitable[dict[str, Any]]], *, ttl: timedelta = timedelta(minutes=15),
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> None:
        self.loader, self.ttl, self.clock = loader, ttl, clock
        self._catalogue: MarketCatalogue | None = None

    async def get_catalogue(self, *, refresh: bool = False) -> MarketCatalogue:
        now = self.clock()
        if not refresh and self._catalogue and self._catalogue.fetched_at and now-self._catalogue.fetched_at < self.ttl:
            return MarketCatalogue(DERIV_PROVIDER, self._catalogue.fetched_at, self._catalogue.instruments, "AVAILABLE", "HIT")
        try:
            instruments = adapt_active_symbols(await self.loader())
            if not instruments: raise MarketDataError("Deriv returned no valid active symbols")
            self._catalogue = MarketCatalogue(DERIV_PROVIDER, now, instruments, "AVAILABLE", "REFRESHED")
        except Exception as exc:
            if self._catalogue:
                return MarketCatalogue(DERIV_PROVIDER, self._catalogue.fetched_at, self._catalogue.instruments,
                    "UNAVAILABLE", "STALE", str(exc))
            return MarketCatalogue(DERIV_PROVIDER, None, (), "UNAVAILABLE", "EMPTY", str(exc))
        return self._catalogue

    async def require_instrument(self, provider_symbol: str) -> MarketInstrument:
        catalogue = await self.get_catalogue()
        match = next((item for item in catalogue.instruments if item.provider_symbol == provider_symbol), None)
        if match is None: raise MarketDataError("Instrument is not present in the validated Deriv catalogue", symbol=provider_symbol)
        return match
