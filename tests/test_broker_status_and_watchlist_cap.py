"""Tests for Stage 6 broker status and watchlist cap usage endpoints."""

from __future__ import annotations

import datetime
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest

from api.app import create_app
from api.routes import (
    get_broker_status as route_get_broker_status,
    get_watchlist_cap_usage as route_get_watchlist_cap_usage,
)
from api.service import ApplicationService
from broker.demo_guard import DEFAULT_BROKER_EVIDENCE_PATH
from config.settings import settings
from data.watchlist import WatchlistStore
from execution.daily_instrument_guard import DailyInstrumentTradeGuard
from execution.safety import (
    DailyStateAuthority,
    EmergencyStopState,
    ExecutionAuthorization,
    ExecutionMode,
    ExecutionSafetySnapshot,
    SQLiteExecutionSafetyStore,
)


def test_get_broker_status_service_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_safety_path = tmp_path / "safety.sqlite3"
    fake_evidence_path = tmp_path / "evidence.sqlite3"
    monkeypatch.setattr(settings, "execution_safety_store_path", fake_safety_path)
    monkeypatch.setattr("api.service.DEFAULT_BROKER_EVIDENCE_PATH", fake_evidence_path)

    service = ApplicationService()
    status = service.get_broker_status()

    assert status.active_broker == settings.effective_broker
    assert status.observation_state in ("NOT_OBSERVED", "UNAVAILABLE")
    assert [b.broker for b in status.brokers] == ["weltrade"]


def test_get_broker_status_with_evidence_and_safety(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_safety_path = tmp_path / "safety.sqlite3"
    fake_evidence_path = tmp_path / "evidence.sqlite3"
    monkeypatch.setattr(settings, "execution_safety_store_path", fake_safety_path)
    monkeypatch.setattr("api.service.DEFAULT_BROKER_EVIDENCE_PATH", fake_evidence_path)
    monkeypatch.setattr(settings, "deriv_options_account_id", "VRTC123456")

    # Write safety snapshot
    safety_store = SQLiteExecutionSafetyStore(fake_safety_path, initialize=True)
    safety_store.publish(
        ExecutionSafetySnapshot(
            observed_at=datetime.datetime.now(datetime.timezone.utc),
            emergency_stop_state=EmergencyStopState.CLEAR,
            execution_mode=ExecutionMode.DURABLE,
            broker="weltrade",
            environment="development",
            durable_executor_enabled=True,
            daily_state_authority=DailyStateAuthority.AUTHORITATIVE,
            unresolved_intent_count=0,
            unresolved_intent_blocked=False,
            execution_authorization=ExecutionAuthorization.AUTHORIZED,
            reason_codes=("AUTHORIZED",),
        )
    )

    monkeypatch.setattr(settings, "weltrade_demo_login", 123456)
    # Write fresh broker verification in evidence store
    verified_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    facts = {"broker": "weltrade", "account_id": "123456", "checked_field": "trade_mode",
             "observed_value": 0, "check": "PASSED", "verified_at": verified_at}
    with sqlite3.connect(fake_evidence_path) as conn:
        conn.execute(
            """
            CREATE TABLE broker_account_verifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                broker TEXT NOT NULL,
                account_id TEXT NOT NULL,
                checked_field TEXT NOT NULL,
                observed_value INTEGER NOT NULL,
                status TEXT NOT NULL,
                verified_at TEXT NOT NULL,
                facts_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO broker_account_verifications
            (session_id, broker, account_id, checked_field, observed_value, status, verified_at, facts_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("sess1", "weltrade", "123456", "trade_mode", 0, "PASSED", verified_at, json.dumps(facts)),
        )

    service = ApplicationService()
    status = service.get_broker_status()

    assert status.emergency_stop_state == "CLEAR"
    assert status.execution_authorization == "AUTHORIZED"
    assert status.observation_state == "OBSERVED"

    weltrade_b = next(b for b in status.brokers if b.broker == "weltrade")
    assert weltrade_b.demo_guard_status == "PASSED"
    assert weltrade_b.demo_guard_verified_at == verified_at
    assert weltrade_b.account_id_masked == "**3456"


def _seed_evidence(path: Path, broker: str, account_id: str, status: str = "PASSED",
                   *, checked_field: str = "trade_mode", observed_value: int = 0,
                   verified_at: str | None = None, facts_json: str | None = None) -> None:
    verified_at = verified_at or datetime.datetime.now(datetime.timezone.utc).isoformat()
    facts_json = facts_json if facts_json is not None else json.dumps({
        "broker": broker, "account_id": account_id, "checked_field": checked_field,
        "observed_value": observed_value, "check": status, "verified_at": verified_at,
    })
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS broker_account_verifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                broker TEXT NOT NULL,
                account_id TEXT NOT NULL,
                checked_field TEXT NOT NULL,
                observed_value INTEGER NOT NULL,
                status TEXT NOT NULL,
                verified_at TEXT NOT NULL,
                facts_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO broker_account_verifications
            (session_id, broker, account_id, checked_field, observed_value, status, verified_at, facts_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("sess-attr", broker, account_id, checked_field, observed_value, status, verified_at, facts_json),
        )


def test_get_broker_status_withholds_unattributable_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_evidence_path = tmp_path / "evidence.sqlite3"
    monkeypatch.setattr(settings, "execution_safety_store_path", tmp_path / "safety.sqlite3")
    monkeypatch.setattr("api.service.DEFAULT_BROKER_EVIDENCE_PATH", fake_evidence_path)
    monkeypatch.setattr(settings, "weltrade_login", 5550001)
    monkeypatch.setattr(settings, "weltrade_demo_login", None)

    _seed_evidence(fake_evidence_path, "weltrade", "9990001")

    status = ApplicationService().get_broker_status()

    weltrade_b = next(b for b in status.brokers if b.broker == "weltrade")
    assert weltrade_b.demo_guard_status == "UNVERIFIED"
    assert weltrade_b.demo_guard_verified_at is None
    assert weltrade_b.notes is not None
    assert "not the configured" in weltrade_b.notes
    assert weltrade_b.account_id_masked == "***0001"


def test_get_broker_status_attributes_weltrade_evidence_to_weltrade(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_evidence_path = tmp_path / "evidence.sqlite3"
    monkeypatch.setattr(settings, "execution_safety_store_path", tmp_path / "safety.sqlite3")
    monkeypatch.setattr("api.service.DEFAULT_BROKER_EVIDENCE_PATH", fake_evidence_path)
    monkeypatch.setattr(settings, "weltrade_login", 5550001)
    monkeypatch.setattr(settings, "weltrade_demo_login", None)

    _seed_evidence(fake_evidence_path, "weltrade", "5550001")

    status = ApplicationService().get_broker_status()

    weltrade_b = next(b for b in status.brokers if b.broker == "weltrade")
    assert [b.broker for b in status.brokers] == ["weltrade"]
    assert weltrade_b.demo_guard_status == "PASSED"
    assert weltrade_b.demo_guard_verified_at is not None
    assert weltrade_b.notes is None


@pytest.mark.parametrize("account_id,checked_field,observed_value,status,age_seconds,facts_json", [
    ("", "trade_mode", 0, "PASSED", 0, None),
    ("UNKNOWN_WELTRADE", "trade_mode", 0, "PASSED", 0, None),
    ("5550001", "is_virtual", 0, "PASSED", 0, None),
    ("5550001", "trade_mode", 2, "PASSED", 0, None),
    ("5550001", "trade_mode", 0, "FAILED", 0, None),
    ("5550001", "trade_mode", 0, "PASSED", 60, None),
    ("5550001", "trade_mode", 0, "PASSED", 0, "not-json"),
])
def test_weltrade_status_rejects_invalid_or_stale_demo_evidence(
    tmp_path, monkeypatch, account_id, checked_field, observed_value, status, age_seconds, facts_json,
) -> None:
    evidence_path = tmp_path / "evidence.sqlite3"
    monkeypatch.setattr(settings, "execution_safety_store_path", tmp_path / "safety.sqlite3")
    monkeypatch.setattr("api.service.DEFAULT_BROKER_EVIDENCE_PATH", evidence_path)
    monkeypatch.setattr(settings, "weltrade_demo_login", 5550001)
    verified_at = (datetime.datetime.now(datetime.timezone.utc)
                   - datetime.timedelta(seconds=age_seconds)).isoformat()
    _seed_evidence(evidence_path, "weltrade", account_id, status, checked_field=checked_field,
                   observed_value=observed_value, verified_at=verified_at, facts_json=facts_json)

    result = ApplicationService().get_broker_status()
    item = result.brokers[0]
    assert item.demo_guard_status == "UNVERIFIED"
    assert item.demo_guard_verified_at is None
    assert item.account_trade_mode is None
    assert result.active_broker_identity is not None
    assert result.active_broker_identity.demo_guard_passed is False
    assert result.active_broker_identity.trade_mode == "UNKNOWN"


def test_legacy_mt5_evidence_is_not_relabelled_weltrade(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_evidence_path = tmp_path / "evidence.sqlite3"
    monkeypatch.setattr(settings, "execution_safety_store_path", tmp_path / "safety.sqlite3")
    monkeypatch.setattr(settings, "broker_selection_store_path", tmp_path / "broker-selection.sqlite3")
    monkeypatch.setattr(settings, "broker", "weltrade")
    monkeypatch.setattr(settings, "mt5_login", None)
    monkeypatch.setattr(settings, "mt5_server", None)
    monkeypatch.setattr(settings, "weltrade_login", 8111)
    monkeypatch.setattr(settings, "weltrade_demo_login", None)
    monkeypatch.setattr("api.service.DEFAULT_BROKER_EVIDENCE_PATH", fake_evidence_path)

    _seed_evidence(fake_evidence_path, "mt5", "8111")

    status = ApplicationService().get_broker_status()
    assert [b.broker for b in status.brokers] == ["weltrade"]
    weltrade_b = next(b for b in status.brokers if b.broker == "weltrade")

    assert weltrade_b.demo_guard_status == "UNVERIFIED"
    assert weltrade_b.account_id_masked == "8111"


@pytest.mark.asyncio
async def test_live_broker_status_reconciles_active_connection_with_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "execution_safety_store_path", tmp_path / "safety.sqlite3")
    monkeypatch.setattr(settings, "broker_selection_store_path", tmp_path / "broker-selection.sqlite3")
    monkeypatch.setattr(settings, "broker", "weltrade")
    monkeypatch.setattr(settings, "weltrade_login", 8111)
    monkeypatch.setattr(settings, "weltrade_demo_login", None)
    monkeypatch.setattr("api.service.DEFAULT_BROKER_EVIDENCE_PATH", tmp_path / "evidence.sqlite3")
    service = ApplicationService()

    async def fake_execution():
        return SimpleNamespace(connected=True)

    monkeypatch.setattr(service, "get_execution_state", fake_execution)
    status = await service.get_live_broker_status()

    assert status.connected is True
    assert status.live_connection_state == "CONNECTED"
    assert status.observation_state == "LIVE"
    assert status.live_checked_at is not None
    assert status.snapshot_observation_state in {"NOT_OBSERVED", "UNAVAILABLE"}
    assert status.snapshot_observed_at is None
    assert next(item for item in status.brokers if item.is_active).connected is True


@pytest.mark.asyncio
async def test_live_status_uses_demo_evidence_recorded_by_current_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence_path = tmp_path / "evidence.sqlite3"
    monkeypatch.setattr(settings, "execution_safety_store_path", tmp_path / "safety.sqlite3")
    monkeypatch.setattr("api.service.DEFAULT_BROKER_EVIDENCE_PATH", evidence_path)
    monkeypatch.setattr(settings, "weltrade_demo_login", 5550001)
    service = ApplicationService()

    async def fake_execution():
        _seed_evidence(evidence_path, "weltrade", "5550001")
        return SimpleNamespace(connected=True)

    monkeypatch.setattr(service, "get_execution_state", fake_execution)
    result = await service.get_live_broker_status()
    assert result.identity_state == "PASSED"
    assert result.active_broker_identity is not None
    assert result.active_broker_identity.demo_guard_passed is True


def test_get_watchlist_cap_usage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_watchlist_path = tmp_path / "watchlist.sqlite3"
    fake_guard_path = tmp_path / "guard.sqlite3"
    monkeypatch.setattr(settings, "watchlist_store_path", fake_watchlist_path)
    monkeypatch.setattr(settings, "daily_instrument_trade_store_path", fake_guard_path)
    monkeypatch.setattr(settings, "max_daily_trades_per_instrument", 10)

    # Seed watchlist
    w_store = WatchlistStore(fake_watchlist_path)

    # Consume some trades using DailyInstrumentTradeGuard
    guard = DailyInstrumentTradeGuard(fake_guard_path, limit=10)
    guard.consume("default", "FX VOL 20")
    guard.consume("default", "FX VOL 20")
    guard.consume("default", "FX VOL 20")

    service = ApplicationService()
    resp = service.get_watchlist_cap_usage(account_scope="default")

    assert len(resp.items) >= 2
    fx_vol_20 = next(i for i in resp.items if i.symbol == "FX VOL 20")
    assert fx_vol_20.daily_count == 3
    assert fx_vol_20.daily_limit == 10
    assert fx_vol_20.daily_remaining == 7
    assert fx_vol_20.available is True

    fx = next(i for i in resp.items if i.symbol == "SFX VOL 20")
    assert fx.daily_count == 0
    assert fx.daily_limit == 10
    assert fx.daily_remaining == 10
    assert fx.available is True


@pytest.mark.asyncio
async def test_api_endpoints_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    app = create_app()
    paths = app.openapi()["paths"]
    assert "/api/v1/brokers/status" in paths
    assert "/api/v1/watchlist/cap-usage" in paths

    service = ApplicationService()
    async def live_status():
        return service.get_broker_status()
    monkeypatch.setattr(service, "get_live_broker_status", live_status)
    # Test route_get_broker_status handler
    resp_b = await route_get_broker_status(service=service)
    assert resp_b.active_broker is not None
    assert len(resp_b.brokers) > 0

    # Test route_get_watchlist_cap_usage handler
    resp_w = route_get_watchlist_cap_usage(account_scope="default", service=service)
    assert isinstance(resp_w.items, list)
