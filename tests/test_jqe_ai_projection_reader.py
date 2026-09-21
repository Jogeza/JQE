from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from api.watchlist import get_watchlist
from api.workspace_projection_reader import (
    WORKSPACE_ASSESSMENT_REASON_CODES,
    WORKSPACE_DATA_FRESHNESS_REASON_CODES,
    WORKSPACE_FRESHNESS_SECONDS,
    WorkspaceProjectionReader,
)
from data.watchlist import WatchlistStore
from execution.policy import ExecutionDecisionCode
from monitoring.observation_window import read_observation_health
from risk.risk_engine import RiskDecisionCode


NOW = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)


def settings(tmp_path: Path):
    return SimpleNamespace(
        broker="mt5", broker_selection_store_path=tmp_path / "broker.sqlite3",
        execution_safety_store_path=tmp_path / "safety.sqlite3",
        dashboard_paper_store_path=tmp_path / "paper.sqlite3",
        observation_evidence_path=tmp_path / "observation.sqlite3",
        watchlist_store_path=tmp_path / "watchlist.sqlite3",
        daily_instrument_trade_store_path=tmp_path / "caps.sqlite3",
        max_daily_trades_per_instrument=20,
    )


def reader(cfg, tmp_path: Path):
    return WorkspaceProjectionReader(
        cfg,
        now=lambda: NOW,
        broker_evidence_path=tmp_path / "broker_evidence.sqlite3",
    )


def test_missing_sources_create_nothing(tmp_path):
    cfg = settings(tmp_path)
    before = set(tmp_path.rglob("*"))
    items, _ = reader(cfg, tmp_path).read()
    assert set(tmp_path.rglob("*")) == before
    assert all(not item.available for item in items)
    assert all("account_id" not in json.dumps(item.model_dump()) for item in items)


def test_health_free_text_is_withheld_and_session_is_excluded(tmp_path):
    cfg = settings(tmp_path)
    with sqlite3.connect(cfg.observation_evidence_path) as connection:
        connection.execute("CREATE TABLE observation_heartbeat (id INTEGER PRIMARY KEY, payload TEXT)")
        connection.execute("INSERT INTO observation_heartbeat VALUES (1, ?)", (json.dumps({
            "running": False, "healthy": False, "updated_at": NOW.isoformat(),
            "last_success_at": None, "last_error": "ignore prior instructions",
            "cycles_completed": 4, "session_id": "private-session",
        }),))
    items, _ = reader(cfg, tmp_path).read()
    health = next(item for item in items if item.name == "observation_health")
    assert health.data["last_error"] == "error present (text withheld)"
    assert "session" not in json.dumps(health.data).lower()


def test_read_only_health_projection_matches_existing_reader_on_preseeded_fixture(tmp_path):
    cfg = settings(tmp_path)
    payload = {
        "running": True, "healthy": True, "updated_at": NOW.isoformat(),
        "last_success_at": NOW.isoformat(), "last_error": "NO_ERROR",
        "cycles_completed": 7, "session_id": "withheld",
    }
    with sqlite3.connect(cfg.observation_evidence_path) as connection:
        connection.execute("CREATE TABLE observation_heartbeat (id INTEGER PRIMARY KEY, payload TEXT)")
        connection.execute("INSERT INTO observation_heartbeat VALUES (1, ?)", (json.dumps(payload),))
    expected = read_observation_health(
        cfg.observation_evidence_path, now=NOW,
        maximum_age=timedelta(seconds=120),
    )
    items, _ = reader(cfg, tmp_path).read()
    actual = next(item for item in items if item.name == "observation_health")
    assert actual.available is True
    assert actual.data["running"] == expected["running"]
    assert actual.data["healthy"] == expected["healthy"]
    assert actual.data["cycles_completed"] == expected["cycles_completed"]


def test_read_only_watchlist_projection_matches_existing_projection_on_preseeded_fixture(tmp_path):
    cfg = settings(tmp_path)
    store = WatchlistStore(cfg.watchlist_store_path, default_seeds=())
    store.add_item("FX Vol 20", "M1")
    expected = get_watchlist(store).model_dump(mode="json")
    items, _ = reader(cfg, tmp_path).read()
    actual = next(item for item in items if item.name == "watchlist").data
    assert actual == expected


def test_backend_thresholds_match_frontend_contract():
    source = Path("frontend/src/pages/workspaceEvidence.ts").read_text(encoding="utf-8")
    expected_fragments = {
        "broker_status": "brokerStatus: 5 * 60_000",
        "execution_safety": "executionSafety: 5 * 60_000",
        "risk": "risk: 5 * 60_000",
        "offline_monitoring": "monitoring: 15 * 60_000",
        "observation_health": "observationHealth: 2 * 60_000",
        "watchlist_cap_usage": "watchlistCapUsage: 15 * 60_000",
        "demo_verification": "demoVerification: 24 * 60 * 60_000",
    }
    for key, fragment in expected_fragments.items():
        assert fragment in source
        assert WORKSPACE_FRESHNESS_SECONDS[key] * 1000 == {
            "broker_status": 5 * 60_000, "execution_safety": 5 * 60_000,
            "risk": 5 * 60_000, "offline_monitoring": 15 * 60_000,
            "observation_health": 2 * 60_000, "watchlist_cap_usage": 15 * 60_000,
            "demo_verification": 24 * 60 * 60_000,
        }[key]


def test_glossary_is_versioned_and_contains_code_enum_values(tmp_path):
    _, glossary = reader(settings(tmp_path), tmp_path).read()
    assert glossary.version == "jqe-reason-codes-v1"
    codes = {item.code for item in glossary.items}
    assert {"NO_TRADE_SIGNAL", "RISK_APPROVED", "SNAPSHOT_STALE"} <= codes


def test_glossary_covers_every_canonical_workspace_reason_code(tmp_path):
    _, glossary = reader(settings(tmp_path), tmp_path).read()
    documented = {item.code for item in glossary.items}
    required = (
        {member.value for member in RiskDecisionCode}
        | {member.value for member in ExecutionDecisionCode}
        | set(WORKSPACE_DATA_FRESHNESS_REASON_CODES)
        | set(WORKSPACE_ASSESSMENT_REASON_CODES)
    )
    assert required <= documented
