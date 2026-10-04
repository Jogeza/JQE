"""Weltrade SyntX Market Scanner and Exploration API Service.

Provides high-efficiency, read-only scanning of all native Weltrade SyntX
synthetic indices across M1, M5, and H1 timeframes. Uses cached terminal
data first (historical.sqlite3 and shadow_mt5_rates.sqlite3), preserving true
broker specifications and labeling data provenance transparently.
"""

from __future__ import annotations

import math
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, Query

from api.dto import (
    ReferralInfoResponse,
    SyntXFamilyDTO,
    SyntXMarketCardDTO,
    SyntXOverviewResponse,
    SyntXSpecsDTO,
)
from broker.types import Candle, TIMEFRAME_SECONDS, Timeframe
from broker.weltrade_symbols import (
    SUPPORTED_WELTRADE_SYNTX,
    SYNTX_FAMILIES,
    canonical_weltrade_symbol,
    get_weltrade_symbol_specs,
    is_weltrade_synthetic,
    list_syntx_families,
    weltrade_symbol_family_id,
    weltrade_symbol_family_name,
    weltrade_symbol_key,
)
from config.settings import settings
from data.storage import CandleStore
from data.watchlist import WatchlistStore

router = APIRouter(prefix="/api/v1", tags=["syntx-markets"])


def _calculate_quick_rsi(closes: list[float], period: int = 14) -> float | None:
    """Calculate RSI from a sequence of closes without third-party dependencies."""
    if len(closes) <= period:
        return None
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(d, 0.0) for d in deltas]
    losses = [max(-d, 0.0) for d in deltas]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0.0:
        return 100.0 if avg_gain > 0.0 else 50.0
    rs = avg_gain / avg_loss
    return round(100.0 - (100.0 / (1.0 + rs)), 2)


def _calculate_quick_atr(
    highs: list[float], lows: list[float], closes: list[float], period: int = 14
) -> float | None:
    """Calculate Average True Range from high, low, close series."""
    if len(closes) <= period or len(highs) != len(closes) or len(lows) != len(closes):
        return None
    tr_list = []
    for i in range(1, len(closes)):
        h = highs[i]
        l = lows[i]
        prev_c = closes[i - 1]
        tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
        tr_list.append(tr)

    if len(tr_list) < period:
        return None
    atr = sum(tr_list[:period]) / period
    for i in range(period, len(tr_list)):
        atr = (atr * (period - 1) + tr_list[i]) / period
    return round(atr, 4)


class SyntXMarketScanService:
    """Read-only market exploration and card projection service for Weltrade SyntX."""

    def __init__(self) -> None:
        self.history_path = settings.historical_data_path
        self.shadow_path = Path("cache/shadow_mt5_rates.sqlite3")
        self.watchlist_path = settings.watchlist_store_path

    def _get_watched_keys(self) -> set[str]:
        """Return canonical symbol keys currently active in the watchlist store."""
        try:
            items = WatchlistStore(self.watchlist_path).get_watchlist(
                provider=settings.effective_broker
            )
            return {weltrade_symbol_key(item.symbol) for item in items}
        except Exception:
            return set()

    def _load_candles_batch(
        self, symbols: list[str], timeframe_str: str, limit: int = 40
    ) -> dict[str, tuple[list[dict], int, str, str | None]]:
        """Load recent candles for all requested symbols using fast index queries.

        Returns a dict mapping canonical symbol -> (candles_list, total_count, provenance).
        """
        tf_clean = timeframe_str.upper()
        result: dict[str, tuple[list[dict], int, str, str | None]] = {}
        remaining: list[str] = list(symbols)

        # Pass 1: historical.sqlite3 (direct single connection using idx_candles_provider_symbol_timeframe_time)
        if self.history_path.exists():
            try:
                con = sqlite3.connect(f"file:{self.history_path}?mode=ro", uri=True)
                cur = con.cursor()
                avail_rows = cur.execute(
                    "SELECT DISTINCT symbol FROM candles WHERE provider = 'weltrade' AND timeframe = ?",
                    (tf_clean,),
                ).fetchall()
                sym_lookup = {r[0]: r[0] for r in avail_rows}

                new_remaining = []
                for canonical in remaining:
                    matched = sym_lookup.get(canonical)
                    if matched:
                        c_row = cur.execute(
                            "SELECT COUNT(*) FROM candles WHERE provider = 'weltrade' AND symbol = ? AND timeframe = ?",
                            (matched, tf_clean),
                        ).fetchone()
                        total = c_row[0] if c_row else 0
                        if total > 0:
                            rows = cur.execute(
                                "SELECT time, open, high, low, close, volume FROM candles "
                                "WHERE provider = 'weltrade' AND symbol = ? AND timeframe = ? "
                                "ORDER BY time DESC LIMIT ?",
                                (matched, tf_clean, limit),
                            ).fetchall()
                            rows.reverse()
                            candles = [
                                {
                                    "time": r[0] if isinstance(r[0], str) else datetime.fromtimestamp(r[0], tz=timezone.utc).isoformat(),
                                    "open": r[1],
                                    "high": r[2],
                                    "low": r[3],
                                    "close": r[4],
                                    "volume": r[5],
                                }
                                for r in rows
                            ]
                            tick_time = None
                            has_ticks = cur.execute(
                                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='ticks'"
                            ).fetchone()
                            if has_ticks:
                                tick_row = cur.execute(
                                    "SELECT time_us FROM ticks WHERE provider='weltrade' "
                                    "AND symbol=? ORDER BY time_us DESC LIMIT 1",
                                    (canonical,),
                                ).fetchone()
                                if tick_row:
                                    tick_time = datetime.fromtimestamp(
                                        tick_row[0] / 1_000_000, tz=timezone.utc
                                    ).isoformat()
                            result[canonical] = (
                                candles, total, "Weltrade MT5 terminal", tick_time
                            )
                            continue
                    new_remaining.append(canonical)
                con.close()
                remaining = new_remaining
            except Exception:
                pass

        # Pass 2: shadow_mt5_rates.sqlite3 for anything still missing (uses sqlite_autoindex_mt5_rates_1 PK)
        if remaining and self.shadow_path.exists():
            try:
                con = sqlite3.connect(f"file:{self.shadow_path}?mode=ro", uri=True)
                cur = con.cursor()
                avail_rows = cur.execute(
                    "SELECT DISTINCT symbol FROM mt5_rates WHERE timeframe = ?",
                    (tf_clean,),
                ).fetchall()
                shadow_lookup = {r[0].lower(): r[0] for r in avail_rows}

                for canonical in remaining:
                    matched = shadow_lookup.get(canonical.lower())
                    if matched:
                        c_row = cur.execute(
                            "SELECT COUNT(*) FROM mt5_rates WHERE symbol = ? AND timeframe = ?",
                            (matched, tf_clean),
                        ).fetchone()
                        total = c_row[0] if c_row else 0
                        if total > 0:
                            rows = cur.execute(
                                "SELECT time, open, high, low, close, tick_volume, spread_points, point "
                                "FROM mt5_rates WHERE symbol = ? AND timeframe = ? "
                                "ORDER BY time DESC LIMIT ?",
                                (matched, tf_clean, limit),
                            ).fetchall()
                            rows.reverse()
                            candles = [
                                {
                                    "time": datetime.fromtimestamp(r[0], tz=timezone.utc).isoformat(),
                                    "open": r[1],
                                    "high": r[2],
                                    "low": r[3],
                                    "close": r[4],
                                    "volume": r[5],
                                    "spread_points": r[6],
                                    "point": r[7],
                                }
                                for r in rows
                            ]
                            result[canonical] = (
                                candles, total, "Weltrade MT5 shadow archive", None
                            )
                con.close()
            except Exception:
                pass

        for canonical in symbols:
            if canonical not in result:
                result[canonical] = ([], 0, "UNAVAILABLE", None)

        return result

    def _load_candles_for_symbol(
        self, symbol: str, timeframe_str: str, limit: int = 40
    ) -> tuple[list[dict], int, str, str | None]:
        """Single-symbol convenience wrapper (used by get_symbol_card)."""
        batch = self._load_candles_batch([symbol], timeframe_str, limit)
        return batch.get(symbol, ([], 0, "UNAVAILABLE", None))

    def get_symbol_card(
        self, symbol: str, timeframe: str = "M5", watched_keys: set[str] | None = None
    ) -> SyntXMarketCardDTO | None:
        """Construct a complete market card for one SyntX instrument."""
        if not is_weltrade_synthetic(symbol):
            return None
        canonical = canonical_weltrade_symbol(symbol)
        raw_specs = get_weltrade_symbol_specs(canonical)
        specs_dto = SyntXSpecsDTO(
            symbol=str(raw_specs["symbol"]),
            family_id=str(raw_specs["family_id"]),
            family_name=str(raw_specs["family_name"]),
            digits=int(raw_specs["digits"]),
            point=float(raw_specs["point"]),
            volume_min=float(raw_specs["volume_min"]),
            volume_step=float(raw_specs["volume_step"]),
            volume_max=float(raw_specs["volume_max"]),
            contract_size=float(raw_specs.get("contract_size", 1.0)),
        )

        if watched_keys is None:
            watched_keys = self._get_watched_keys()
        is_watched = weltrade_symbol_key(canonical) in watched_keys

        candles, total_count, provenance, last_tick_time = self._load_candles_for_symbol(
            canonical, timeframe, limit=35
        )

        if not candles:
            return SyntXMarketCardDTO(
                symbol=canonical,
                family_id=specs_dto.family_id,
                family_name=specs_dto.family_name,
                timeframe=timeframe,
                cache_status="MISSING",
                candle_count=0,
                provenance="UNAVAILABLE",
                freshness_age_seconds=None,
                last_tick_time=last_tick_time,
                last_tick_age_seconds=None,
                is_watched=is_watched,
                specs=specs_dto,
            )

        closes = [c["close"] for c in candles]
        highs = [c["high"] for c in candles]
        lows = [c["low"] for c in candles]
        volumes = [c.get("volume") or 0.0 for c in candles]

        latest_close = closes[-1]
        open_price = candles[0]["open"]
        high_price = max(highs)
        low_price = min(lows)
        change_val = round(latest_close - open_price, specs_dto.digits)
        change_pct = (
            round(((latest_close - open_price) / open_price) * 100, 2)
            if open_price > 0
            else 0.0
        )
        recent_vol = round(sum(volumes[-10:]), 2)

        # Spread estimate from specs/data
        spread_val = None
        if "spread_points" in candles[-1] and "point" in candles[-1]:
            spread_val = round(candles[-1]["spread_points"] * candles[-1]["point"], specs_dto.digits)

        atr_val = _calculate_quick_atr(highs, lows, closes, period=14)
        rsi_val = _calculate_quick_rsi(closes, period=14)
        sparkline = [round(v, specs_dto.digits) for v in closes[-20:]]

        timeframe_enum = Timeframe(timeframe.upper())
        latest_open = datetime.fromisoformat(candles[-1]["time"])
        if latest_open.tzinfo is None:
            latest_open = latest_open.replace(tzinfo=timezone.utc)
        close_time = latest_open.astimezone(timezone.utc) + timedelta(
            seconds=TIMEFRAME_SECONDS[timeframe_enum]
        )
        now = datetime.now(timezone.utc)
        freshness_age = max(0.0, (now - close_time).total_seconds())
        stale_after = max(120, TIMEFRAME_SECONDS[timeframe_enum] * 2)
        cache_status: Literal["CACHED", "PARTIAL", "MISSING", "STALE", "UNAVAILABLE"] = (
            "STALE" if freshness_age > stale_after
            else "CACHED" if total_count >= 50
            else "PARTIAL"
        )
        tick_age = None
        if last_tick_time is not None:
            tick_datetime = datetime.fromisoformat(last_tick_time).astimezone(timezone.utc)
            tick_age = max(0.0, (now - tick_datetime).total_seconds())

        return SyntXMarketCardDTO(
            symbol=canonical,
            family_id=specs_dto.family_id,
            family_name=specs_dto.family_name,
            timeframe=timeframe,
            latest_close=latest_close,
            open_price=open_price,
            high_price=high_price,
            low_price=low_price,
            change_pct=change_pct,
            change_value=change_val,
            volume=recent_vol,
            spread=spread_val,
            atr=atr_val,
            rsi=rsi_val,
            sparkline=sparkline,
            cache_status=cache_status,
            candle_count=total_count,
            first_candle_time=candles[0]["time"],
            last_candle_time=candles[-1]["time"],
            freshness_age_seconds=round(freshness_age, 1),
            last_tick_time=last_tick_time,
            last_tick_age_seconds=None if tick_age is None else round(tick_age, 1),
            provenance=provenance,
            is_watched=is_watched,
            specs=specs_dto,
        )

    def get_syntx_overview(
        self,
        timeframe: str = "M5",
        family_filter: str = "all",
        search: str = "",
    ) -> SyntXOverviewResponse:
        """Scan and assemble market cards for all Weltrade SyntX symbols."""
        watched_keys = self._get_watched_keys()
        instruments: list[SyntXMarketCardDTO] = []
        cached_count = 0

        clean_search = search.strip().lower()
        clean_family = family_filter.strip().lower()

        # Pre-filter symbols so we only batch-load what the caller needs
        candidates: list[str] = []
        for sym in SUPPORTED_WELTRADE_SYNTX:
            canonical = canonical_weltrade_symbol(sym)
            fid = weltrade_symbol_family_id(canonical)
            fname = weltrade_symbol_family_name(canonical)
            if clean_family != "all" and fid != clean_family:
                continue
            if clean_search:
                match_text = f"{canonical} {fname} {fid}".lower()
                if clean_search not in match_text:
                    continue
            candidates.append(canonical)

        # Single batch load for all candidates
        candle_map = self._load_candles_batch(candidates, timeframe, limit=35)

        for canonical in candidates:
            raw_specs = get_weltrade_symbol_specs(canonical)
            specs_dto = SyntXSpecsDTO(
                symbol=str(raw_specs["symbol"]),
                family_id=str(raw_specs["family_id"]),
                family_name=str(raw_specs["family_name"]),
                digits=int(raw_specs["digits"]),
                point=float(raw_specs["point"]),
                volume_min=float(raw_specs["volume_min"]),
                volume_step=float(raw_specs["volume_step"]),
                volume_max=float(raw_specs["volume_max"]),
                contract_size=float(raw_specs.get("contract_size", 1.0)),
            )
            is_watched = weltrade_symbol_key(canonical) in watched_keys
            candles, total_count, provenance, last_tick_time = candle_map.get(
                canonical, ([], 0, "UNAVAILABLE", None)
            )

            if not candles:
                instruments.append(SyntXMarketCardDTO(
                    symbol=canonical,
                    family_id=specs_dto.family_id,
                    family_name=specs_dto.family_name,
                    timeframe=timeframe,
                    cache_status="MISSING",
                    candle_count=0,
                    last_tick_time=last_tick_time,
                    provenance="UNAVAILABLE",
                    is_watched=is_watched,
                    specs=specs_dto,
                ))
                continue

            closes = [c["close"] for c in candles]
            highs = [c["high"] for c in candles]
            lows = [c["low"] for c in candles]
            volumes = [c.get("volume") or 0.0 for c in candles]
            latest_close = closes[-1]
            open_price = candles[0]["open"]
            high_price = max(highs)
            low_price = min(lows)
            change_val = round(latest_close - open_price, specs_dto.digits)
            change_pct = (
                round(((latest_close - open_price) / open_price) * 100, 2)
                if open_price > 0 else 0.0
            )
            recent_vol = round(sum(volumes[-10:]), 2)
            spread_val = None
            if "spread_points" in candles[-1] and "point" in candles[-1]:
                spread_val = round(candles[-1]["spread_points"] * candles[-1]["point"], specs_dto.digits)
            atr_val = _calculate_quick_atr(highs, lows, closes, period=14)
            rsi_val = _calculate_quick_rsi(closes, period=14)
            sparkline = [round(v, specs_dto.digits) for v in closes[-20:]]
            timeframe_enum = Timeframe(timeframe.upper())
            latest_open = datetime.fromisoformat(candles[-1]["time"])
            if latest_open.tzinfo is None:
                latest_open = latest_open.replace(tzinfo=timezone.utc)
            close_time = latest_open.astimezone(timezone.utc) + timedelta(
                seconds=TIMEFRAME_SECONDS[timeframe_enum]
            )
            now = datetime.now(timezone.utc)
            freshness_age = max(0.0, (now - close_time).total_seconds())
            stale_after = max(120, TIMEFRAME_SECONDS[timeframe_enum] * 2)
            cache_status: Literal["CACHED", "PARTIAL", "MISSING", "STALE", "UNAVAILABLE"] = (
                "STALE" if freshness_age > stale_after
                else "CACHED" if total_count >= 50
                else "PARTIAL"
            )
            tick_age = None
            if last_tick_time is not None:
                tick_age = max(
                    0.0,
                    (now - datetime.fromisoformat(last_tick_time).astimezone(timezone.utc)).total_seconds(),
                )
            if cache_status in {"CACHED", "PARTIAL", "STALE"}:
                cached_count += 1

            instruments.append(SyntXMarketCardDTO(
                symbol=canonical,
                family_id=specs_dto.family_id,
                family_name=specs_dto.family_name,
                timeframe=timeframe,
                latest_close=latest_close,
                open_price=open_price,
                high_price=high_price,
                low_price=low_price,
                change_pct=change_pct,
                change_value=change_val,
                volume=recent_vol,
                spread=spread_val,
                atr=atr_val,
                rsi=rsi_val,
                sparkline=sparkline,
                cache_status=cache_status,
                candle_count=total_count,
                first_candle_time=candles[0]["time"],
                last_candle_time=candles[-1]["time"],
                freshness_age_seconds=round(freshness_age, 1),
                last_tick_time=last_tick_time,
                last_tick_age_seconds=None if tick_age is None else round(tick_age, 1),
                provenance=provenance,
                is_watched=is_watched,
                specs=specs_dto,
            ))

        # Families list DTO
        families_dto = [
            SyntXFamilyDTO(id=f["id"], name=f["name"], description=f["description"])
            for f in list_syntx_families()
        ]

        return SyntXOverviewResponse(
            timeframe=timeframe,
            total_instruments=len(SUPPORTED_WELTRADE_SYNTX),
            cached_instruments=cached_count,
            families=families_dto,
            instruments=instruments,
            weltrade_referral_url=settings.weltrade_referral_url,
            refreshed_at=datetime.now(timezone.utc).isoformat(),
        )

    def get_referral_info(self) -> ReferralInfoResponse:
        """Return configured Weltrade partner/referral destination."""
        return ReferralInfoResponse(
            referral_url=settings.weltrade_referral_url,
            broker="weltrade",
            status="ACTIVE",
        )


_scan_service = SyntXMarketScanService()


@router.get("/syntx/overview", response_model=SyntXOverviewResponse)
def get_syntx_overview(
    timeframe: str = Query(default="M5", pattern="^(M1|M5|H1)$"),
    family: str = Query(default="all"),
    search: str = Query(default=""),
) -> SyntXOverviewResponse:
    """Return overview with market cards for all native Weltrade SyntX instruments."""
    return _scan_service.get_syntx_overview(timeframe=timeframe, family_filter=family, search=search)


@router.get("/syntx/families", response_model=list[SyntXFamilyDTO])
def get_syntx_families() -> list[SyntXFamilyDTO]:
    """Return verified Weltrade SyntX symbol families for filtering."""
    return [
        SyntXFamilyDTO(id=f["id"], name=f["name"], description=f["description"])
        for f in list_syntx_families()
    ]


@router.get("/syntx/card/{symbol}", response_model=SyntXMarketCardDTO)
def get_syntx_symbol_card(
    symbol: str,
    timeframe: str = Query(default="M5", pattern="^(M1|M5|H1)$"),
) -> SyntXMarketCardDTO:
    """Return detailed market card and indicators for a single SyntX instrument."""
    card = _scan_service.get_symbol_card(symbol, timeframe=timeframe)
    if card is None:
        raise ValueError(f"Unknown or out-of-scope Weltrade SyntX symbol: {symbol}")
    return card


@router.get("/referral", response_model=ReferralInfoResponse)
def get_referral_info() -> ReferralInfoResponse:
    """Return configured Weltrade referral and partner registration link."""
    return _scan_service.get_referral_info()
