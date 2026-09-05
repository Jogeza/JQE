from datetime import datetime, timedelta, timezone

import pytest

from research.markets import MarketCatalogueService, adapt_active_symbols


def entry(symbol="frxEURUSD", name="EUR/USD", market="forex", submarket="major_pairs", **changes):
    value = {"underlying_symbol": symbol, "underlying_symbol_name": name,
        "underlying_symbol_type": market, "market": market, "subgroup": "none",
        "submarket": submarket, "pip_size": 0.00001, "exchange_is_open": 1,
        "is_trading_suspended": 0}
    value.update(changes); return value


def test_current_schema_adaptation_identity_categories_suspension_and_order():
    payload = {"active_symbols": [
        entry("CRYBTCUSD", "BTC/USD", "cryptocurrency", "non_stable_coin"),
        entry("R_100", "Volatility 100 Index", "synthetic_index", "random_index"),
        entry("frxEURUSD", "EUR/USD", is_trading_suspended=1),
        entry("OTC_UNKNOWN", "Future Market", "future_category", "new_submarket"),
        {"market": "malformed"},
    ]}
    items = adapt_active_symbols(payload)
    assert len(items) == 4
    eur = next(item for item in items if item.provider_symbol == "frxEURUSD")
    assert eur.canonical_symbol == "EURUSD" and eur.display_name == "EUR/USD"
    assert eur.is_trading_suspended and eur.provider_symbol != eur.display_name
    assert any(item.market == "future_category" for item in items)
    assert items == tuple(sorted(items, key=lambda item: (item.market, item.submarket, item.display_name.casefold(), item.provider_symbol)))


def test_deliberate_legacy_smartcharts_shape_is_normalized():
    legacy = {"symbol": "WLDAUD", "display_name": "AUD Basket", "symbol_type": "forex_basket",
        "market": "basket_index", "market_display_name": "Basket Indices", "submarket": "forex_basket",
        "submarket_display_name": "Forex Basket", "pip": .001, "exchange_is_open": 1,
        "is_trading_suspended": 0}
    item = adapt_active_symbols({"active_symbols": [legacy]})[0]
    assert item.provider_symbol == "WLDAUD" and item.market_display_name == "Basket Indices"


@pytest.mark.asyncio
async def test_catalogue_ttl_cache_expiry_and_stale_fallback():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc); calls = 0
    async def loader():
        nonlocal calls; calls += 1
        if calls == 3: raise RuntimeError("public outage")
        return {"active_symbols": [entry()]}
    clock_value = [now]
    service = MarketCatalogueService(loader, ttl=timedelta(minutes=5), clock=lambda: clock_value[0])
    assert (await service.get_catalogue()).cache_status == "REFRESHED"
    assert (await service.get_catalogue()).cache_status == "HIT" and calls == 1
    clock_value[0] += timedelta(minutes=6)
    assert (await service.get_catalogue()).cache_status == "REFRESHED" and calls == 2
    clock_value[0] += timedelta(minutes=6)
    stale = await service.get_catalogue()
    assert stale.source_status == "UNAVAILABLE" and stale.cache_status == "STALE"
    assert len(stale.instruments) == 1


@pytest.mark.asyncio
async def test_catalogue_only_calls_loader_and_never_acquires_history():
    calls = []
    async def loader(): calls.append("active_symbols"); return {"active_symbols": [entry()]}
    await MarketCatalogueService(loader).get_catalogue()
    assert calls == ["active_symbols"]
