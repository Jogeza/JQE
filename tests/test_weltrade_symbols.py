"""Weltrade synthetic symbol scope, canonical spelling, and cache identity."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from broker.types import Candle, Timeframe
from broker.weltrade_symbols import (
    canonical_weltrade_symbol,
    is_weltrade_synthetic,
    require_weltrade_synthetic,
    weltrade_symbol_key,
)
from core.exceptions import MarketDataError
from data.storage import CandleStore
from data.watchlist import WatchlistStore


CANONICAL_CASES = [
    ("FX VOL 20", "FX Vol 20"),
    ("FX Vol 20", "FX Vol 20"),
    ("fx vol 20", "FX Vol 20"),
    ("FX  VOL.  20", "FX Vol 20"),
    ("SFX VOL 99", "SFX Vol 99"),
    ("sfx vol 20", "SFX Vol 20"),
    ("PAINX 400", "PainX 400"),
    ("painx 1200", "PainX 1200"),
    ("MAX PAINX 1000", "MAX PainX 1000"),
    ("max gainx 2000", "MAX GainX 2000"),
    ("GAINX 400", "GainX 400"),
    ("FLIPX 1", "FlipX 1"),
    ("switchx 2", "SwitchX 2"),
    ("BREAKX 3", "BreakX 3"),
    ("FIBOX", "FiboX"),
    ("  fibox  ", "FiboX"),
]

OUT_OF_SCOPE = [
    "R_75", "R_10", "frxXAUUSD", "XAUUSD", "TrendX 1000", "PlusX 1",
    "FX Vol", "MAX FIBOX", "FIBOX 1", "", "   ",
]


@pytest.mark.parametrize(("raw", "expected"), CANONICAL_CASES)
def test_canonical_uses_terminal_catalogue_casing(raw: str, expected: str) -> None:
    assert canonical_weltrade_symbol(raw) == expected


@pytest.mark.parametrize(("raw", "expected"), CANONICAL_CASES)
def test_require_returns_canonical_spelling(raw: str, expected: str) -> None:
    assert require_weltrade_synthetic(raw) == expected


@pytest.mark.parametrize("raw", OUT_OF_SCOPE)
def test_out_of_scope_fails_closed(raw: str) -> None:
    assert is_weltrade_synthetic(raw) is False
    with pytest.raises(MarketDataError):
        canonical_weltrade_symbol(raw)
    with pytest.raises(MarketDataError):
        require_weltrade_synthetic(raw)


def test_watchlist_and_terminal_spellings_share_one_identity() -> None:
    """The durable watchlist upper-cases; the terminal catalogue does not.

    Both spellings must resolve to the same key or one instrument fragments
    into cached datasets that no exact-equality match can reunite.
    """
    assert weltrade_symbol_key("SFX VOL 20") == weltrade_symbol_key("SFX Vol 20")
    assert weltrade_symbol_key("FX VOL. 20") == weltrade_symbol_key("FX Vol 20")
    assert weltrade_symbol_key("MAX PAINX 1000") == weltrade_symbol_key("MAX PainX 1000")
    assert weltrade_symbol_key("FX Vol 20") != weltrade_symbol_key("FX Vol 40")
    assert weltrade_symbol_key("FX Vol 20") != weltrade_symbol_key("SFX Vol 20")


def _seed_store(path: Path, symbol: str) -> CandleStore:
    store = CandleStore(path)
    start = datetime(2026, 9, 26, 2, 30, tzinfo=timezone.utc)
    candles = [
        Candle(
            time=start + timedelta(minutes=5 * index),
            open=100.0 + index, high=102.0 + index,
            low=99.0 + index, close=101.0 + index,
            volume=10.0 + index, source="test",
        )
        for index in range(6)
    ]
    store.save_candles(symbol, Timeframe.M5, candles, provider="weltrade")
    return store


async def test_research_markets_resolves_cache_across_casing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: `/markets` read `item.symbol`, which CachedDatasetSummary
    does not define. The bare `except` swallowed the AttributeError and every
    instrument reported NOT CACHED regardless of whether history existed."""
    from api import research as research_module

    history_path = tmp_path / "historical.sqlite3"
    watchlist_path = tmp_path / "watchlist.sqlite3"
    _seed_store(history_path, "SFX Vol 20")
    WatchlistStore(watchlist_path, default_seeds=[("SFX Vol 20", "M5")])

    monkeypatch.setattr(
        research_module, "settings",
        SimpleNamespace(
            historical_data_path=history_path,
            watchlist_store_path=watchlist_path,
            effective_broker="weltrade",
        ),
    )

    payload = await research_module.get_research_markets()

    assert payload["watchlist_count"] == 1
    assert payload["watchlist"][0]["symbol"] == "SFX VOL 20"
    cached = payload["cached_datasets"]
    assert len(cached) == 1, "terminal-cased history must survive the upper-cased watchlist"
    assert cached[0]["canonical_symbol"] == "SFX Vol 20"
    assert cached[0]["candle_count"] == 6


async def test_research_markets_reports_empty_when_cache_unreadable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing cache is still a legitimate empty answer, not an error."""
    from api import research as research_module

    watchlist_path = tmp_path / "watchlist.sqlite3"
    WatchlistStore(watchlist_path, default_seeds=[("SFX Vol 20", "M5")])

    monkeypatch.setattr(
        research_module, "settings",
        SimpleNamespace(
            historical_data_path=tmp_path / "absent.sqlite3",
            watchlist_store_path=watchlist_path,
            effective_broker="weltrade",
        ),
    )

    payload = await research_module.get_research_markets()

    assert payload["cached_datasets"] == []
    assert payload["watchlist_count"] == 1


def test_symbol_families_and_specs() -> None:
    from broker.weltrade_symbols import (
        weltrade_symbol_family_id,
        weltrade_symbol_family_name,
        get_weltrade_symbol_specs,
        list_syntx_families,
        list_supported_weltrade_synthetics,
    )

    assert weltrade_symbol_family_id("FX Vol 20") == "fx_vol"
    assert weltrade_symbol_family_name("FX Vol 20") == "FX Volatility"
    assert weltrade_symbol_family_id("sfx vol 40") == "sfx_vol"
    assert weltrade_symbol_family_id("MAX PainX 1000") == "max_painx"
    assert weltrade_symbol_family_id("painx 400") == "painx"
    assert weltrade_symbol_family_id("FiboX") == "fibox"
    assert weltrade_symbol_family_id("flipx 1") == "flipx"
    assert weltrade_symbol_family_id("switchx 600") == "switchx"
    assert weltrade_symbol_family_id("breakx 1200") == "breakx"

    max_specs = get_weltrade_symbol_specs("MAX PainX 1000")
    assert max_specs["digits"] == 3
    assert max_specs["point"] == 0.001
    assert max_specs["volume_min"] == 0.01

    pain_specs = get_weltrade_symbol_specs("PainX 400")
    assert pain_specs["digits"] == 2
    assert pain_specs["point"] == 0.01
    assert pain_specs["volume_min"] == 0.1

    families = list_syntx_families()
    assert len(families) >= 8
    assert any(f["id"] == "fx_vol" for f in families)

    all_symbols = list_supported_weltrade_synthetics()
    assert len(all_symbols) == 36
    assert "FX Vol 20" in all_symbols
    assert "SFX Vol 20" in all_symbols
    assert "PainX 400" in all_symbols
