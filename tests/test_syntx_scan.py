"""Unit tests for Weltrade SyntX market scan endpoints and service."""

import pytest
import sqlite3
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient

from api.app import app
from api.market_scan import SyntXMarketScanService
from broker.weltrade_symbols import SUPPORTED_WELTRADE_SYNTX, list_syntx_families


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Explicit synthetic fixtures keep API tests independent of operator archives.
    import api.market_scan as market_scan
    service = SyntXMarketScanService()
    service.history_path = tmp_path / "history.sqlite3"
    service.shadow_path = tmp_path / "absent-shadow.sqlite3"
    service.watchlist_path = tmp_path / "watchlist.sqlite3"
    with sqlite3.connect(service.history_path) as connection:
        connection.execute("CREATE TABLE candles (provider TEXT, symbol TEXT, timeframe TEXT, time TEXT, open REAL, high REAL, low REAL, close REAL, volume REAL)")
        now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        for symbol in ("FX Vol 20", "SFX Vol 20"):
            connection.executemany("INSERT INTO candles VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", [
                ("weltrade", symbol, "M5", (now - timedelta(minutes=5 * (40 - index))).isoformat(), 100 + index, 102 + index, 99 + index, 101 + index, 10)
                for index in range(40)
            ])
    monkeypatch.setattr(market_scan, "_scan_service", service)
    return TestClient(app)


def test_list_syntx_families():
    families = list_syntx_families()
    assert len(families) >= 5
    family_ids = [f["id"] for f in families]
    assert "fx_vol" in family_ids
    assert "sfx_vol" in family_ids
    assert "painx" in family_ids
    assert "max_painx" in family_ids


def test_api_syntx_families(client):
    response = client.get("/api/v1/syntx/families")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 5
    first = data[0]
    assert "id" in first
    assert "name" in first
    assert "description" in first


def test_api_referral_info(client):
    response = client.get("/api/v1/referral")
    assert response.status_code == 200
    data = response.json()
    assert data["broker"] == "weltrade"
    assert data["status"] == "ACTIVE"
    assert "track.gowt.me" in data["referral_url"] or "weltrade" in data["referral_url"]


def test_api_syntx_overview_all(client):
    response = client.get("/api/v1/syntx/overview?timeframe=M5&family=all&search=")
    assert response.status_code == 200
    data = response.json()
    assert data["timeframe"] == "M5"
    assert data["total_instruments"] == len(SUPPORTED_WELTRADE_SYNTX)
    assert data["cached_instruments"] >= 1
    assert len(data["instruments"]) == len(SUPPORTED_WELTRADE_SYNTX)
    assert len(data["families"]) >= 5
    assert "referral_url" in data["weltrade_referral_url"] or "weltrade" in data["weltrade_referral_url"]


def test_api_syntx_overview_filtered_family(client):
    response = client.get("/api/v1/syntx/overview?timeframe=M5&family=painx&search=")
    assert response.status_code == 200
    data = response.json()
    assert len(data["instruments"]) > 0
    for inst in data["instruments"]:
        assert inst["family_id"] == "painx"


def test_api_syntx_overview_search(client):
    response = client.get("/api/v1/syntx/overview?timeframe=M5&family=all&search=SFX+Vol+20")
    assert response.status_code == 200
    data = response.json()
    assert len(data["instruments"]) == 1
    assert data["instruments"][0]["symbol"] == "SFX Vol 20"
    assert data["instruments"][0]["cache_status"] in ("CACHED", "PARTIAL", "STALE")
    assert data["instruments"][0]["latest_close"] is not None
    assert data["instruments"][0]["provenance"] == "Weltrade MT5 terminal"
    assert data["instruments"][0]["freshness_age_seconds"] is not None
    assert "change_value" in data["instruments"][0]
    assert "first_candle_time" in data["instruments"][0]
    assert "last_candle_time" in data["instruments"][0]


def test_api_syntx_symbol_card_valid(client):
    response = client.get("/api/v1/syntx/card/FX%20Vol%2020?timeframe=M5")
    assert response.status_code == 200
    card = response.json()
    assert card["symbol"] == "FX Vol 20"
    assert card["family_id"] == "fx_vol"
    assert card["specs"]["digits"] == 2
    assert card["specs"]["contract_size"] == 1.0


def test_syntx_scan_service_unit():
    service = SyntXMarketScanService()
    card = service.get_symbol_card("FX Vol 20", timeframe="M5")
    assert card is not None
    assert card.symbol == "FX Vol 20"
    assert card.specs.family_id == "fx_vol"

    # Out-of-scope symbol must return None
    invalid_card = service.get_symbol_card("INVALID_DERIV_SYNTHETIC", timeframe="M5")
    assert invalid_card is None
