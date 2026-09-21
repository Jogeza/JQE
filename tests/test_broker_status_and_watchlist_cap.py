"""Tests for Stage 6 broker status and watchlist cap usage endpoints."""

from __future__ import annotations

import datetime
from pathlib import Path
import sqlite3

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
    assert len(status.brokers) == 4
    # Check that brokers contain mt5, weltrade, deriv, simulation
    broker_names = [b.broker for b in status.brokers]
    assert "mt5" in broker_names
    assert "weltrade" in broker_names
    assert "deriv" in broker_names
    assert "simulation" in broker_names


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
            broker="deriv",
            environment="development",
            durable_executor_enabled=True,
            daily_state_authority=DailyStateAuthority.AUTHORITATIVE,
            unresolved_intent_count=0,
            unresolved_intent_blocked=False,
            execution_authorization=ExecutionAuthorization.AUTHORIZED,
            reason_codes=("AUTHORIZED",),
        )
    )

    # Write broker verification in evidence store
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
            ("sess1", "deriv", "VRTC123456", "is_virtual", 1, "PASSED", "2026-09-17T12:00:00+00:00", "{}"),
        )

    service = ApplicationService()
    status = service.get_broker_status()

    assert status.emergency_stop_state == "CLEAR"
    assert status.execution_authorization == "AUTHORIZED"
    assert status.observation_state == "OBSERVED"

    # Find deriv broker
    deriv_b = next(b for b in status.brokers if b.broker == "deriv")
    assert deriv_b.demo_guard_status == "PASSED"
    assert deriv_b.demo_guard_verified_at == "2026-09-17T12:00:00+00:00"
    assert deriv_b.account_id_masked == "******3456"


def _seed_evidence(path: Path, broker: str, account_id: str, status: str = "PASSED") -> None:
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
            ("sess-attr", broker, account_id, "trade_mode", 0, status, "2026-09-18T09:00:00+00:00", "{}"),
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
    mt5_b = next(b for b in status.brokers if b.broker == "mt5")
    assert weltrade_b.demo_guard_status == "PASSED"
    assert weltrade_b.demo_guard_verified_at == "2026-09-18T09:00:00+00:00"
    assert weltrade_b.notes is None
    assert mt5_b.demo_guard_status == "UNVERIFIED"
    assert mt5_b.demo_guard_verified_at is None


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
    guard.consume("default", "R_75")
    guard.consume("default", "R_75")
    guard.consume("default", "R_75")

    service = ApplicationService()
    resp = service.get_watchlist_cap_usage(account_scope="default")

    assert len(resp.items) >= 2
    r75 = next(i for i in resp.items if i.symbol == "R_75")
    assert r75.daily_count == 3
    assert r75.daily_limit == 10
    assert r75.daily_remaining == 7
    assert r75.available is True

    fx = next(i for i in resp.items if i.symbol == "FX VOL 20")
    assert fx.daily_count == 0
    assert fx.daily_limit == 10
    assert fx.daily_remaining == 10
    assert fx.available is True


def test_api_endpoints_routes() -> None:
    app = create_app()
    paths = app.openapi()["paths"]
    assert "/api/v1/brokers/status" in paths
    assert "/api/v1/watchlist/cap-usage" in paths

    service = ApplicationService()
    # Test route_get_broker_status handler
    resp_b = route_get_broker_status(service=service)
    assert resp_b.active_broker is not None
    assert len(resp_b.brokers) > 0

    # Test route_get_watchlist_cap_usage handler
    resp_w = route_get_watchlist_cap_usage(account_scope="default", service=service)
    assert isinstance(resp_w.items, list)

