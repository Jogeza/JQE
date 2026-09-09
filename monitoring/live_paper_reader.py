"""Read-only projections over live-paper evidence and position-ledger SQLite files."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any


FEED_EVENT_TYPES = frozenset({
    "SIGNAL", "CANDIDATE", "CONFIRMATION", "ENTRY", "RISK", "POLICY",
    "POSITION_OPENED", "POSITION_CLOSED",
})
CRITICAL_REASON_CODES = frozenset({
    "UNMATCHED_DERIV_POSITION_ON_STARTUP",
    "BROKER_POSITION_MISMATCH",
    "ORDER_RATE_LIMIT",
    "RECOVERED_VIA_MT5_TAG_FALLBACK",
    "DUPLICATE_IDEMPOTENCY_KEY",
    "ENTRY_TIMEOUT",
})


def _read_only_connection(path: Path) -> sqlite3.Connection:
    """Open an existing SQLite database without create, journal, or write access."""
    resolved = path.expanduser().resolve(strict=True)
    connection = sqlite3.connect(
        f"{resolved.as_uri()}?mode=ro",
        uri=True,
        timeout=0.1,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    connection.execute("PRAGMA busy_timeout=100")
    return connection


def _events(path: Path, session_id: str) -> list[dict[str, Any]]:
    with _read_only_connection(path) as connection:
        rows = connection.execute(
            "SELECT rowid, payload FROM evidence WHERE session_id=? ORDER BY rowid DESC",
            (session_id,),
        ).fetchall()
    return [{**json.loads(row["payload"]), "sequence": row["rowid"]} for row in rows]


def _sessions(path: Path) -> list[dict[str, Any]]:
    with _read_only_connection(path) as connection:
        rows = connection.execute(
            "SELECT rowid, session_id, fingerprint, status FROM campaign ORDER BY rowid DESC"
        ).fetchall()
    result = []
    for row in rows:
        fingerprint = json.loads(row["fingerprint"])
        config = fingerprint.get("effective_config", {})
        result.append({
            "session_id": row["session_id"],
            "state": str(row["status"]).lower(),
            "broker": config.get("broker"),
            "symbol": fingerprint.get("symbol") or config.get("symbol"),
            "timeframe": fingerprint.get("timeframe") or config.get("timeframe"),
            "started_at": fingerprint.get("first_candle"),
            "stop_conditions": config.get("stop_conditions", {}),
        })
    return result


def _ledger_rows(path: Path) -> list[dict[str, Any]]:
    with _read_only_connection(path) as connection:
        rows = connection.execute(
            """
            SELECT broker, symbol, position_id, order_id, opened_at, closed_at
            FROM live_paper_positions ORDER BY opened_at DESC, position_id
            """
        ).fetchall()
    return [dict(row) for row in rows]


def _is_alert(event: dict[str, Any]) -> bool:
    facts = event.get("facts", {})
    return (
        facts.get("reason_code") in CRITICAL_REASON_CODES
        or (event.get("event_type") == "ENTRY" and facts.get("result") == "REJECTED")
    )


def _session_progress(session: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    observations = [e for e in events if e.get("event_type") == "OBSERVATION"]
    candles = max(
        (int(e.get("facts", {}).get("candles_processed", 0)) for e in observations),
        default=0,
    )
    stop = session.get("stop_conditions", {})
    started_at = session.get("started_at")
    elapsed = None
    if started_at:
        try:
            started = datetime.fromisoformat(started_at)
            end = datetime.now(timezone.utc)
            if session.get("state") != "running" and events:
                end = datetime.fromisoformat(events[0]["occurred_at"])
            elapsed = max(0.0, (end - started).total_seconds())
        except (TypeError, ValueError):
            pass
    return {
        "candles_observed": candles,
        "max_candles": stop.get("max_candles"),
        "elapsed_seconds": elapsed,
        "max_duration_seconds": stop.get("max_duration_seconds"),
    }


def _open_positions(
    ledger: list[dict[str, Any]], events: list[dict[str, Any]], broker: str | None,
) -> list[dict[str, Any]]:
    open_rows = [row for row in ledger if row["closed_at"] is None and row["broker"] == broker]
    latest_snapshot: dict[str, dict[str, Any]] = {}
    for event in events:
        if event.get("event_type") == "POSITION_SNAPSHOT":
            latest_snapshot = {
                str(position.get("position_id")): position
                for position in event.get("facts", {}).get("positions", [])
            }
            break

    recovery: dict[str, str] = {}
    event_details: dict[str, dict[str, Any]] = {}
    for event in reversed(events):
        facts = event.get("facts", {})
        position_id = facts.get("position_id") or facts.get("broker_order_id")
        if not position_id:
            continue
        if event.get("event_type") == "POSITION_OPENED":
            event_details[str(position_id)] = facts
        reason = facts.get("reason_code")
        if reason == "POSITION_RECOVERED_ON_STARTUP":
            recovery[str(position_id)] = "Local ledger"
            event_details[str(position_id)] = facts
        elif reason == "RECOVERED_VIA_MT5_TAG_FALLBACK":
            recovery[str(position_id)] = "MT5 tag fallback"
            event_details[str(position_id)] = facts

    positions = []
    for row in open_rows:
        position_id = row["position_id"]
        observed = latest_snapshot.get(position_id, {})
        details = event_details.get(position_id, {})
        positions.append({
            **row,
            "side": observed.get("side", details.get("side")),
            "size": observed.get("volume", details.get("filled_volume", details.get("volume"))),
            "entry_price": observed.get("open_price", details.get("broker_fill_price", details.get("open_price"))),
            "current_price": observed.get("current_price"),
            "stop_loss": observed.get("stop_loss", details.get("stop_loss")),
            "take_profit": observed.get("take_profit", details.get("take_profit")),
            "recovered": position_id in recovery,
            "recovery_path": recovery.get(position_id),
            "present_in_latest_broker_snapshot": position_id in latest_snapshot,
        })
    return positions


def _closed_positions(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    opened: dict[str, dict[str, Any]] = {}
    for event in reversed(events):
        if event.get("event_type") == "POSITION_OPENED":
            facts = event.get("facts", {})
            key = str(facts.get("position_id") or facts.get("broker_order_id"))
            opened[key] = facts
    result = []
    for event in events:
        if event.get("event_type") != "POSITION_CLOSED":
            continue
        facts = event.get("facts", {})
        key = str(facts.get("position_id") or facts.get("broker_order_id"))
        entry = opened.get(key, {})
        result.append({
            "position_id": key,
            "symbol": facts.get("symbol"),
            "side": facts.get("side"),
            "closed_at": event.get("occurred_at"),
            "exit_reason": facts.get("exit_reason"),
            "requested_price": entry.get("requested_price"),
            "filled_price": entry.get("broker_fill_price"),
            "slippage": entry.get("slippage"),
            "exit_price": facts.get("exit_price"),
            "pnl": facts.get("pnl"),
        })
    return result


def dashboard_snapshot(
    evidence_path: Path,
    ledger_path: Path,
    session_id: str | None = None,
    *,
    feed_limit: int = 100,
) -> dict[str, Any]:
    """Build one immutable dashboard payload from read-only database snapshots."""
    sessions = _sessions(evidence_path)
    if not sessions:
        return {"sessions": [], "selected_session": None, "alerts": [], "open_positions": [], "recent_evidence": [], "closed_positions": []}
    selected = next((item for item in sessions if item["session_id"] == session_id), sessions[0])
    events = _events(evidence_path, selected["session_id"])
    ledger = _ledger_rows(ledger_path)
    stopped = next((e for e in events if e.get("event_type") == "CAMPAIGN_STOPPED"), None)
    selected = {
        **selected,
        "progress": _session_progress(selected, events),
        "stop_reason": stopped.get("facts", {}).get("stop_reason") if stopped else None,
    }
    return {
        "sessions": sessions,
        "selected_session": selected,
        "alerts": [event for event in events if _is_alert(event)],
        "open_positions": _open_positions(ledger, events, selected.get("broker")),
        "recent_evidence": [event for event in events if event.get("event_type") in FEED_EVENT_TYPES][:feed_limit],
        "closed_positions": _closed_positions(events)[:feed_limit],
        "refreshed_at": datetime.now(timezone.utc).isoformat(),
    }
