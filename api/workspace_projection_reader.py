"""Read-only adapters for the seven Workspace evidence sources.

Every SQLite connection uses ``mode=ro``. Missing or malformed evidence becomes
an unavailable item; this module never initializes, repairs, or writes a store.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from jqe_ai.models import ContextItem, GlossaryBundle, GlossaryEntry
from monitoring.observation_window import read_observation_health
from execution.policy import ExecutionDecisionCode
from risk.risk_engine import RiskDecisionCode

WORKSPACE_FRESHNESS_SECONDS = {
    "broker_status": 5 * 60,
    "execution_safety": 5 * 60,
    "risk": 5 * 60,
    "offline_monitoring": 15 * 60,
    "observation_health": 2 * 60,
    "watchlist": None,
    "watchlist_cap_usage": 15 * 60,
    "demo_verification": 24 * 60 * 60,
}

_KNOWN_ERROR = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_SOURCES = {
    "broker_status": "GET /api/v1/brokers/status",
    "execution_safety": "GET /api/v1/execution/safety",
    "risk": "GET /api/v1/risk",
    "offline_monitoring": "GET /api/v1/monitoring/offline",
    "observation_health": "GET /api/v1/observation/health",
    "watchlist": "GET /api/v1/watchlist",
    "watchlist_cap_usage": "GET /api/v1/watchlist/cap-usage",
}

WORKSPACE_DATA_FRESHNESS_REASON_CODES = frozenset({
    "LATEST_CLOSED_CANDLE_WITHIN_TOLERANCE",
    "DATA_NOT_FRESH",
    "CANDLE_FORMING",
    "SETUP_EXPIRED",
    "SNAPSHOT_STALE",
    "SNAPSHOT_UNAVAILABLE",
})
WORKSPACE_ASSESSMENT_REASON_CODES = frozenset({
    "NO_TRADE", "ANALYSIS_ONLY", "INVALID_TRADE_PLAN", "RISK_REJECTED",
    "RISK_AUTHORIZED", "QUANTITY_NOT_VERIFIABLE", "NOT_OBSERVED",
    "NOT_EVALUATED", "DEMO_DAILY_SUBMISSION_CAP_REACHED",
})


def _connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True, timeout=1.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=1000")
    return connection


def _one(path: Path, query: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        with _connect(path) as connection:
            row = connection.execute(query, params).fetchone()
            return None if row is None else dict(row)
    except (sqlite3.Error, OSError):
        return None


def _many(path: Path, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]] | None:
    if not path.is_file():
        return None
    try:
        with _connect(path) as connection:
            return [dict(row) for row in connection.execute(query, params).fetchall()]
    except (sqlite3.Error, OSError):
        return None


def _instant(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except ValueError:
        return None


def _item(name: str, data: dict[str, Any] | None, observed_at: str | None, now: datetime) -> ContextItem:
    instant = _instant(observed_at)
    age = None if instant is None else max(0.0, (now - instant).total_seconds())
    threshold = WORKSPACE_FRESHNESS_SECONDS[name]
    return ContextItem(
        name=name, source=_SOURCES[name], observed_at=observed_at, age_seconds=age,
        stale=bool(data is not None and threshold is not None and (age is None or age > threshold)),
        available=data is not None, data=data or {},
    )


def _humanize(code: str) -> str:
    return code.replace("_", " ").lower().capitalize() + "."


def build_glossary() -> GlossaryBundle:
    codes = {member.value for member in RiskDecisionCode}
    codes.update(member.value for member in ExecutionDecisionCode)
    codes.update(WORKSPACE_DATA_FRESHNESS_REASON_CODES)
    codes.update(WORKSPACE_ASSESSMENT_REASON_CODES)
    return GlossaryBundle(
        version="jqe-reason-codes-v1",
        items=[GlossaryEntry(code=code, meaning=_humanize(code)) for code in sorted(codes)],
    )


class WorkspaceProjectionReader:
    def __init__(
        self,
        settings,
        *,
        now=lambda: datetime.now(timezone.utc),
        broker_evidence_path: Path = Path("state/broker_evidence.sqlite3"),
    ) -> None:
        self.settings = settings
        self._now = now
        self._broker_evidence_path = broker_evidence_path

    def _active_broker(self) -> str:
        configured = str(self.settings.broker).removesuffix("_demo")
        path = Path(self.settings.broker_selection_store_path)
        row = _one(path, "SELECT selected_broker FROM broker_selection WHERE id=1")
        return str(row["selected_broker"]) if row and row.get("selected_broker") else configured

    def _safety_row(self) -> dict[str, Any] | None:
        return _one(Path(self.settings.execution_safety_store_path), "SELECT * FROM execution_safety_snapshot WHERE singleton_id=1")

    def _broker(self, now: datetime, safety: dict[str, Any] | None) -> ContextItem:
        active = self._active_broker()
        observed = safety.get("observed_at") if safety else None
        evidence = _one(
            self._broker_evidence_path,
            "SELECT status, verified_at FROM broker_account_verifications WHERE lower(broker)=? ORDER BY id DESC LIMIT 1",
            (active,),
        )
        verified_at = evidence.get("verified_at") if evidence else None
        verified_age = None
        verified_instant = _instant(verified_at)
        if verified_instant:
            verified_age = max(0.0, (now - verified_instant).total_seconds())
        data = None if safety is None and evidence is None else {
            "active_broker": active,
            "connected": bool(safety),
            "observation_state": "OBSERVED" if safety else "NOT_OBSERVED",
            "demo_verified_identity_present": bool(
                evidence and evidence.get("status") == "PASSED" and verified_age is not None
                and verified_age <= WORKSPACE_FRESHNESS_SECONDS["demo_verification"]
            ),
            "demo_verified_at": verified_at,
            "demo_verification_stale": bool(verified_age is not None and verified_age > WORKSPACE_FRESHNESS_SECONDS["demo_verification"]),
        }
        return _item("broker_status", data, observed, now)

    def _safety(self, now: datetime, row: dict[str, Any] | None) -> ContextItem:
        data = None if row is None else {
            "observation_state": "OBSERVED", "emergency_stop_state": row.get("emergency_stop_state"),
            "execution_mode": row.get("execution_mode"), "broker": row.get("broker"),
            "durable_executor_enabled": bool(row.get("durable_executor_enabled")),
            "daily_state_authority": row.get("daily_state_authority"),
            "unresolved_intent_count": row.get("unresolved_intent_count"),
            "unresolved_intent_blocked": bool(row.get("unresolved_intent_blocked")),
            "execution_authorization": row.get("execution_authorization"),
            "reason_codes": str(row.get("reason_codes") or "").splitlines(),
        }
        return _item("execution_safety", data, row.get("observed_at") if row else None, now)

    def _risk(self, now: datetime) -> ContextItem:
        row = _one(Path(self.settings.execution_safety_store_path), "SELECT * FROM risk_authorization_snapshot WHERE singleton_id=1")
        data = None if row is None else {
            "evaluation_state": row.get("evaluation_state"), "currency": row.get("currency"),
            "daily_trades_count": row.get("daily_trades_count"), "daily_loss_percent": row.get("daily_loss_percent"),
            "risk_allowed": bool(row.get("risk_allowed")), "risk_message": row.get("risk_message"),
            "rejection_reason": row.get("rejection_reason"), "authorized_risk_percent": row.get("authorized_risk_percent"),
            "quantity_available": bool(row.get("execution_quantity_available")),
            "quantity_unit": row.get("execution_quantity_unit"), "quantity_reason": row.get("execution_quantity_reason"),
        }
        return _item("risk", data, row.get("observed_at") if row else None, now)

    def _monitoring(self, now: datetime) -> ContextItem:
        row = _one(Path(self.settings.dashboard_paper_store_path), "SELECT payload FROM market_setups ORDER BY created_at DESC LIMIT 1")
        if not row:
            return _item("offline_monitoring", None, None, now)
        try:
            setup = json.loads(row["payload"])
        except (TypeError, json.JSONDecodeError):
            return _item("offline_monitoring", None, None, now)
        data = {
            "assessment": {
                "symbol": setup.get("symbol"), "timeframe": setup.get("timeframe"),
                "direction": setup.get("direction"), "setup_state": setup.get("setup_state"),
                "confidence_score": setup.get("confidence_score"), "evidence": setup.get("evidence", []),
                "data_freshness": setup.get("data_freshness"),
                "risk_authorization": setup.get("risk_authorization"),
                "execution_authorization": setup.get("execution_authorization"),
                "reason_codes": setup.get("reason_codes", []),
            }
        }
        return _item("offline_monitoring", data, setup.get("observed_at"), now)

    def _health(self, now: datetime) -> ContextItem:
        path = Path(self.settings.observation_evidence_path)
        if not path.is_file():
            return _item("observation_health", None, None, now)
        maximum_age = timedelta(seconds=WORKSPACE_FRESHNESS_SECONDS["observation_health"])
        payload = read_observation_health(path, now=now, maximum_age=maximum_age)
        if payload.get("last_error") and not _KNOWN_ERROR.fullmatch(str(payload["last_error"])):
            last_error = "error present (text withheld)"
        else:
            last_error = payload.get("last_error")
        data = {
            "running": payload.get("running"), "healthy": payload.get("healthy"),
            "last_success_at": payload.get("last_success_at"), "last_error": last_error,
            "cycles_completed": payload.get("cycles_completed"),
        }
        return _item("observation_health", data, payload.get("updated_at"), now)

    def _watchlist(self, now: datetime) -> tuple[ContextItem, list[dict[str, Any]] | None]:
        rows = _many(Path(self.settings.watchlist_store_path), "SELECT symbol, timeframe, added_at FROM watchlist ORDER BY rowid ASC")
        if rows is not None:
            rows = [{**row, "scope": f"{row['symbol']}:{row['timeframe']}"} for row in rows]
        data = None if rows is None else {"items": rows, "count": len(rows)}
        return _item("watchlist", data, None, now), rows

    def _caps(self, now: datetime, watchlist: list[dict[str, Any]] | None) -> ContextItem:
        path = Path(self.settings.daily_instrument_trade_store_path)
        if watchlist is None or not path.is_file():
            return _item("watchlist_cap_usage", None, None, now)
        day = now.date().isoformat()
        rows = _many(path, "SELECT instrument, submission_starts FROM daily_instrument_trade_counter WHERE scope=? AND utc_date=?", ("default", day))
        if rows is None:
            return _item("watchlist_cap_usage", None, None, now)
        counts = {str(row["instrument"]): int(row["submission_starts"]) for row in rows}
        limit = int(self.settings.max_daily_trades_per_instrument)
        data = {"items": [
            {"symbol": item["symbol"], "timeframe": item["timeframe"], "scope": "default",
             "daily_count": counts.get(item["symbol"], 0), "daily_limit": limit,
             "daily_remaining": max(0, limit - counts.get(item["symbol"], 0)),
             "available": counts.get(item["symbol"], 0) < limit}
            for item in watchlist
        ]}
        return _item("watchlist_cap_usage", data, now.isoformat(), now)

    def read(self) -> tuple[list[ContextItem], GlossaryBundle]:
        now = self._now().astimezone(timezone.utc)
        safety = self._safety_row()
        watchlist_item, watchlist_rows = self._watchlist(now)
        items = [
            self._broker(now, safety), self._safety(now, safety), self._risk(now),
            self._monitoring(now), self._health(now), watchlist_item,
            self._caps(now, watchlist_rows),
        ]
        return items, build_glossary()
