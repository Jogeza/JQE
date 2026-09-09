"""Read-only projections and HTTP surface for the live-paper monitor."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3

import pytest

from monitoring.dashboard import create_dashboard
from monitoring.live_paper_reader import dashboard_snapshot


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _databases(tmp_path: Path) -> tuple[Path, Path]:
    evidence = tmp_path / "campaign.evidence.sqlite3"
    ledger = tmp_path / "campaign.positions.sqlite3"
    fingerprint = {
        "effective_config": {
            "broker": "mt5_demo",
            "symbol": "XAUUSD",
            "timeframe": "M15",
            "stop_conditions": {"max_candles": 20},
        },
        "symbol": "XAUUSD",
        "timeframe": "M15",
        "first_candle": "2026-09-09T10:00:00+00:00",
    }
    events = [
        ("OBSERVATION", "2026-09-09T10:15:00+00:00", {"candles_processed": 7}),
        ("POSITION_OPENED", "2026-09-09T10:16:00+00:00", {
            "position_id": "P-OPEN", "broker_order_id": "O-OPEN", "symbol": "XAUUSD",
            "side": "BUY", "requested_price": 2000.0, "broker_fill_price": 2000.5,
            "filled_volume": 0.2, "slippage": 0.5, "stop_loss": 1990.0,
            "take_profit": 2020.0,
        }),
        ("POLICY", "2026-09-09T10:17:00+00:00", {
            "reason_code": "POSITION_RECOVERED_ON_STARTUP", "position_id": "P-OPEN",
            "side": "BUY", "volume": 0.2, "open_price": 2000.5,
        }),
        ("POSITION_SNAPSHOT", "2026-09-09T10:18:00+00:00", {"positions": [{
            "position_id": "P-OPEN", "symbol": "XAUUSD", "side": "BUY",
            "volume": 0.2, "open_price": 2000.5, "current_price": 2004.0,
            "stop_loss": 1991.0, "take_profit": 2021.0,
            "opened_at": "2026-09-09T10:16:00+00:00",
        }]}),
        ("ENTRY", "2026-09-09T10:19:00+00:00", {
            "result": "REJECTED", "reason_code": "ORDER_RATE_LIMIT",
        }),
        ("POSITION_OPENED", "2026-09-09T09:00:00+00:00", {
            "position_id": "P-CLOSED", "broker_order_id": "O-CLOSED", "symbol": "XAUUSD",
            "side": "SELL", "requested_price": 2010.0, "broker_fill_price": 2009.5,
            "slippage": 0.5,
        }),
        ("POSITION_CLOSED", "2026-09-09T09:30:00+00:00", {
            "position_id": "P-CLOSED", "broker_order_id": "O-CLOSED", "symbol": "XAUUSD",
            "side": "SELL", "exit_reason": "BROKER_TP", "exit_price": 1990.0, "pnl": 19.5,
        }),
    ]
    with sqlite3.connect(evidence) as connection:
        connection.execute("CREATE TABLE campaign(session_id TEXT PRIMARY KEY,fingerprint TEXT,status TEXT)")
        connection.execute("CREATE TABLE evidence(session_id TEXT,event_id TEXT,payload TEXT,PRIMARY KEY(session_id,event_id))")
        connection.execute("INSERT INTO campaign VALUES(?,?,?)", ("SESSION-1", json.dumps(fingerprint), "RUNNING"))
        for index, (event_type, occurred_at, facts) in enumerate(events, 1):
            payload = {"event_id": f"E-{index}", "event_type": event_type, "candidate_id": None, "occurred_at": occurred_at, "facts": facts}
            connection.execute("INSERT INTO evidence VALUES(?,?,?)", ("SESSION-1", f"E-{index}", json.dumps(payload)))
    with sqlite3.connect(ledger) as connection:
        connection.execute("""CREATE TABLE live_paper_positions(
            broker TEXT, symbol TEXT, position_id TEXT, order_id TEXT,
            opened_at TEXT, closed_at TEXT, PRIMARY KEY(broker,position_id))""")
        connection.execute("INSERT INTO live_paper_positions VALUES(?,?,?,?,?,NULL)", (
            "mt5_demo", "XAUUSD", "P-OPEN", "O-OPEN", "2026-09-09T10:16:00+00:00",
        ))
        connection.execute("INSERT INTO live_paper_positions VALUES(?,?,?,?,?,?)", (
            "mt5_demo", "XAUUSD", "P-CLOSED", "O-CLOSED", "2026-09-09T09:00:00+00:00", "2026-09-09T09:30:00+00:00",
        ))
    return evidence, ledger


def test_snapshot_projects_all_required_views_without_modifying_databases(tmp_path):
    evidence, ledger = _databases(tmp_path)
    before = (_digest(evidence), _digest(ledger))
    snapshot = dashboard_snapshot(evidence, ledger)
    after = (_digest(evidence), _digest(ledger))

    assert before == after
    assert snapshot["selected_session"]["state"] == "running"
    assert snapshot["selected_session"]["progress"]["candles_observed"] == 7
    assert snapshot["selected_session"]["progress"]["max_candles"] == 20
    assert snapshot["alerts"][0]["facts"]["reason_code"] == "ORDER_RATE_LIMIT"
    assert snapshot["open_positions"][0]["position_id"] == "P-OPEN"
    assert snapshot["open_positions"][0]["current_price"] == 2004.0
    assert snapshot["open_positions"][0]["stop_loss"] == 1991.0
    assert snapshot["open_positions"][0]["recovery_path"] == "Local ledger"
    assert snapshot["closed_positions"][0]["exit_reason"] == "BROKER_TP"
    assert snapshot["closed_positions"][0]["requested_price"] == 2010.0
    assert snapshot["closed_positions"][0]["filled_price"] == 2009.5


@pytest.mark.asyncio
async def test_http_dashboard_serves_page_and_snapshot(tmp_path):
    evidence, ledger = _databases(tmp_path)
    app = create_dashboard(evidence, ledger)
    routes = {route.path: route.endpoint for route in app.routes if hasattr(route, "endpoint")}
    page = await routes["/"]()
    response = await routes["/api/snapshot"](session_id="SESSION-1", feed_limit=100)
    assert "Critical alerts" in page
    assert response["selected_session"]["session_id"] == "SESSION-1"


def test_dashboard_modules_have_no_execution_or_sqlite_write_path():
    root = Path(__file__).resolve().parents[1]
    sources = "\n".join((root / name).read_text(encoding="utf-8") for name in (
        "monitoring/live_paper_reader.py", "monitoring/dashboard.py",
    ))
    assert "from broker" not in sources
    assert "import broker" not in sources
    assert "execution.persistence" not in sources
    assert "submit_order" not in sources
    for statement in ("INSERT INTO", "UPDATE ", "DELETE FROM", "CREATE TABLE"):
        assert statement not in sources
