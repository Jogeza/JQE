"""Versioned, factual diagnostics for processed paper-runtime observations."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter
from dataclasses import asdict, dataclass, fields
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from statistics import median
from typing import Any, Iterable


SCHEMA_VERSION = 1
STRATEGY_ID = "strategy.pipeline.generate_trading_signal"
_DECIMAL_FIELDS = {
    "signal_confidence", "authorized_quantity", "realized_pnl", "realized_r",
    "fees", "slippage", "cumulative_pnl", "equity", "drawdown",
    "processing_duration_ms", "strategy_duration_ms", "risk_duration_ms",
    "execution_duration_ms", "market_data_freshness_seconds",
}


@dataclass(frozen=True, slots=True)
class PaperObservationRecord:
    session_id: str
    observed_at: datetime
    symbol: str
    timeframe: str
    candle_close_time: datetime
    source_mode: str
    dataset_identity: str | None
    cycle_number: int
    regime: str | None = None
    signal_direction: str = "NO_SIGNAL"
    signal_confidence: Decimal | None = None
    confirmation_state: str = "NOT_EVALUATED"
    execution_decision: str = "NOT_EVALUATED"
    block_reason: str | None = None
    risk_authorization_state: str = "NOT_EVALUATED"
    authorized_quantity: Decimal | None = None
    paper_position_state: str | None = None
    entry_event: str | None = None
    exit_event: str | None = None
    exit_reason: str | None = None
    realized_pnl: Decimal | None = None
    realized_r: Decimal | None = None
    fees: Decimal | None = None
    slippage: Decimal | None = None
    cumulative_pnl: Decimal | None = None
    equity: Decimal | None = None
    drawdown: Decimal | None = None
    processing_duration_ms: Decimal | None = None
    strategy_duration_ms: Decimal | None = None
    risk_duration_ms: Decimal | None = None
    execution_duration_ms: Decimal | None = None
    market_data_freshness_seconds: Decimal | None = None
    reconciliation_state: str = "NOT_EVALUATED"

    def __post_init__(self) -> None:
        if not self.session_id.strip() or not self.symbol.strip() or not self.timeframe.strip():
            raise ValueError("paper observation identity is incomplete")
        if self.observed_at.tzinfo is None or self.candle_close_time.tzinfo is None:
            raise ValueError("paper observation timestamps must be timezone-aware")
        if self.cycle_number <= 0:
            raise ValueError("paper observation cycle must be positive")
        for name in _DECIMAL_FIELDS:
            value = getattr(self, name)
            if value is not None and type(value) is not Decimal:
                raise ValueError(f"{name} must use Decimal authority")


@dataclass(frozen=True, slots=True)
class PaperObservationSession:
    session_id: str
    started_at: datetime
    ended_at: datetime | None
    git_commit: str
    strategy_id: str
    configuration_hash: str
    runtime_mode: str
    source_mode: str
    symbols: tuple[str, ...]
    timeframes: tuple[str, ...]
    dataset_identity: str | None
    status: str = "RUNNING"
    termination_reason: str | None = None

    @property
    def context_identity(self) -> str:
        return ":".join((self.git_commit, self.strategy_id, self.configuration_hash, self.runtime_mode, self.source_mode))


def configuration_hash(values: dict[str, Any]) -> str:
    payload = json.dumps(values, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _encode(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, tuple):
        return list(value)
    return value


def _payload(item: object) -> str:
    return json.dumps({key: _encode(value) for key, value in asdict(item).items()}, sort_keys=True)


def _decode_record(payload: str) -> PaperObservationRecord:
    values = json.loads(payload)
    for name in ("observed_at", "candle_close_time"):
        values[name] = datetime.fromisoformat(values[name])
    for name in _DECIMAL_FIELDS:
        if values.get(name) is not None:
            values[name] = Decimal(values[name])
    return PaperObservationRecord(**values)


class PaperDiagnosticsStore:
    def __init__(self, path: str | Path, *, initialize: bool = True) -> None:
        resolved = Path(path).expanduser().resolve()
        self.path = str(resolved)
        if initialize:
            resolved.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as connection:
                connection.execute("CREATE TABLE IF NOT EXISTS sessions (session_id TEXT PRIMARY KEY, context_identity TEXT NOT NULL, payload TEXT NOT NULL)")
                connection.execute("CREATE TABLE IF NOT EXISTS observations (session_id TEXT NOT NULL, symbol TEXT NOT NULL, timeframe TEXT NOT NULL, candle_close_time TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(session_id,symbol,timeframe,candle_close_time))")

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=5.0)

    def start(self, session: PaperObservationSession) -> None:
        with self._connect() as connection:
            row = connection.execute("SELECT context_identity FROM sessions WHERE session_id=?", (session.session_id,)).fetchone()
            if row is not None and row[0] != session.context_identity:
                raise ValueError("incompatible paper observation session context")
            connection.execute("INSERT OR IGNORE INTO sessions VALUES(?,?,?)", (session.session_id, session.context_identity, _payload(session)))

    def finish(self, session: PaperObservationSession) -> None:
        with self._connect() as connection:
            row = connection.execute("SELECT context_identity FROM sessions WHERE session_id=?", (session.session_id,)).fetchone()
            if row is None or row[0] != session.context_identity:
                raise ValueError("paper observation session context mismatch")
            connection.execute("UPDATE sessions SET payload=? WHERE session_id=?", (_payload(session), session.session_id))

    def append(self, record: PaperObservationRecord) -> bool:
        with self._connect() as connection:
            if connection.execute("SELECT 1 FROM sessions WHERE session_id=?", (record.session_id,)).fetchone() is None:
                raise ValueError("paper observation session is unavailable")
            inserted = connection.execute(
                "INSERT OR IGNORE INTO observations VALUES(?,?,?,?,?)",
                (record.session_id, record.symbol.upper(), record.timeframe, record.candle_close_time.isoformat(), _payload(record)),
            ).rowcount
        return inserted == 1

    def records(self, session_id: str | None = None) -> tuple[PaperObservationRecord, ...]:
        query = "SELECT payload FROM observations"
        args: tuple[str, ...] = ()
        if session_id is not None:
            query += " WHERE session_id=?"
            args = (session_id,)
        query += " ORDER BY candle_close_time, symbol, timeframe"
        with self._connect() as connection:
            rows = connection.execute(query, args).fetchall()
        return tuple(_decode_record(row[0]) for row in rows)

    def session(self, session_id: str) -> PaperObservationSession | None:
        with self._connect() as connection:
            row = connection.execute("SELECT payload FROM sessions WHERE session_id=?", (session_id,)).fetchone()
        if row is None:
            return None
        values = json.loads(row[0])
        values["started_at"] = datetime.fromisoformat(values["started_at"])
        values["ended_at"] = datetime.fromisoformat(values["ended_at"]) if values["ended_at"] else None
        values["symbols"], values["timeframes"] = tuple(values["symbols"]), tuple(values["timeframes"])
        return PaperObservationSession(**values)

    def latest_session(self) -> PaperObservationSession | None:
        with self._connect() as connection:
            row = connection.execute("SELECT payload FROM sessions ORDER BY rowid DESC LIMIT 1").fetchone()
        if row is None:
            return None
        values = json.loads(row[0])
        values["started_at"] = datetime.fromisoformat(values["started_at"])
        values["ended_at"] = datetime.fromisoformat(values["ended_at"]) if values["ended_at"] else None
        values["symbols"], values["timeframes"] = tuple(values["symbols"]), tuple(values["timeframes"])
        return PaperObservationSession(**values)


def _maximum_drawdown(values: Iterable[Decimal]) -> Decimal:
    total = peak = maximum = Decimal("0")
    for value in values:
        total += value
        peak = max(peak, total)
        maximum = max(maximum, peak - total)
    return maximum


def _confidence_bucket(confidence: Decimal | None) -> str:
    if confidence is None:
        return "UNKNOWN"
    value = int(confidence)
    if value <= 20:
        return "0-20"
    if value <= 40:
        return "21-40"
    if value <= 60:
        return "41-60"
    if value <= 80:
        return "61-80"
    return "81-100"


def _classify_block_reason(reason: str | None) -> str:
    if not reason:
        return "NO_BLOCK"
    normalized = reason.upper()
    if any(token in normalized for token in ("NO_SIGNAL", "LOW_CONFIDENCE", "CONFIDENCE", "VOLATILITY", "MOMENTUM", "RSI")):
        return "STRATEGY_FILTERS"
    if "CONFIRMATION" in normalized:
        return "CONFIRMATION_FILTERS"
    if any(token in normalized for token in ("RISK", "POSITION", "LIMIT", "AUTHORIZATION", "CAP", "EXPOSURE")):
        return "RISK_BLOCKS"
    if any(token in normalized for token in ("POLICY", "EXECUTION", "EMERGENCY", "IDEMPOTENCY", "BROKER", "INVALID_TRADE")):
        return "EXECUTION_POLICY_BLOCKS"
    if any(token in normalized for token in ("STALE", "MISSING", "DUPLICATE", "OUT_OF_ORDER", "FORMING", "SOURCE", "AVAILABILITY", "DATA")):
        return "DATA_QUALITY_BLOCKS"
    if any(token in normalized for token in ("STATE", "RESTART", "RECONSTRUCT", "OPEN_POSITION")):
        return "RESTART_STATE_BLOCKS"
    return "STRATEGY_FILTERS"


def summarize(records: Iterable[PaperObservationRecord], *, minimum_sample: int = 100) -> dict[str, Any]:
    items = tuple(records)
    trades = tuple(item for item in items if item.realized_pnl is not None)
    pnls = tuple(item.realized_pnl for item in trades if item.realized_pnl is not None)
    rs = tuple(item.realized_r for item in trades if item.realized_r is not None)
    wins, losses = tuple(x for x in pnls if x > 0), tuple(x for x in pnls if x < 0)
    gross_profit, gross_loss = sum(wins, Decimal("0")), abs(sum(losses, Decimal("0")))
    longest_wins = longest_losses = current_wins = current_losses = 0
    for pnl in pnls:
        current_wins = current_wins + 1 if pnl > 0 else 0
        current_losses = current_losses + 1 if pnl < 0 else 0
        longest_wins, longest_losses = max(longest_wins, current_wins), max(longest_losses, current_losses)

    def group(field: str) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for name in sorted({str(getattr(item, field) or "UNKNOWN") for item in items}):
            subset = tuple(item for item in items if str(getattr(item, field) or "UNKNOWN") == name)
            closed = tuple(item for item in subset if item.realized_pnl is not None)
            result[name] = {
                "observations": len(subset), "signals": sum(item.signal_direction != "NO_SIGNAL" for item in subset),
                "entries": sum(item.entry_event is not None for item in subset), "closed_trades": len(closed),
                "net_pnl": str(sum((item.realized_pnl for item in closed if item.realized_pnl is not None), Decimal("0"))),
                "average_r": str(sum((item.realized_r for item in closed if item.realized_r is not None), Decimal("0")) / len(closed)) if closed and all(item.realized_r is not None for item in closed) else None,
                "block_reasons": dict(Counter(item.block_reason for item in subset if item.block_reason)),
            }
        return result

    exit_distribution = {}
    for reason in sorted({item.exit_reason or "OTHER" for item in trades}):
        subset = tuple(item for item in trades if (item.exit_reason or "OTHER") == reason)
        category_rs = tuple(item.realized_r for item in subset if item.realized_r is not None)
        category_pnls = tuple(item.realized_pnl for item in subset if item.realized_pnl is not None)
        exit_distribution[reason] = {
            "count": len(subset),
            "average_pnl": str(sum(category_pnls, Decimal("0")) / len(category_pnls)) if category_pnls else None,
            "average_r": str(sum(category_rs, Decimal("0")) / len(category_rs)) if category_rs else None,
            "median_r": str(median(category_rs)) if category_rs else None,
        }

    signals = sum(item.signal_direction != "NO_SIGNAL" for item in items)
    confirmations = sum(item.confirmation_state == "CONFIRMED" for item in items)
    authorized_entries = sum(item.execution_decision == "ALLOWED" for item in items)
    opened_positions = sum(item.entry_event is not None for item in items)
    closed_positions = len(trades)
    raw_signal_rate = (Decimal(signals) / Decimal(len(items))) if items else None
    confirmation_rate = (Decimal(confirmations) / Decimal(signals)) if signals else None
    authorization_rate = (Decimal(authorized_entries) / Decimal(confirmations)) if confirmations else None
    entry_rate = (Decimal(opened_positions) / Decimal(authorized_entries)) if authorized_entries else None
    confidence_distribution = {}
    for bucket in ("0-20", "21-40", "41-60", "61-80", "81-100"):
        subset = tuple(item for item in items if _confidence_bucket(item.signal_confidence) == bucket)
        if not subset:
            continue
        confidence_distribution[bucket] = {
            "count": len(subset),
            "signal_directions": dict(Counter(item.signal_direction for item in subset)),
            "confirmations": sum(item.confirmation_state == "CONFIRMED" for item in subset),
            "confirmation_rate": str((Decimal(sum(item.confirmation_state == "CONFIRMED" for item in subset)) / Decimal(len(subset))) * 100) if subset else None,
        }

    rejection_layers = {}
    for layer in ("STRATEGY_FILTERS", "CONFIRMATION_FILTERS", "RISK_BLOCKS", "EXECUTION_POLICY_BLOCKS", "DATA_QUALITY_BLOCKS", "RESTART_STATE_BLOCKS"):
        count = sum(1 for item in items if item.block_reason and _classify_block_reason(item.block_reason) == layer)
        if count:
            rejection_layers[layer] = count

    by_volatility = {
        "LOW_VOLATILITY": {"count": sum(1 for item in items if item.block_reason and "LOW_VOLATILITY" in item.block_reason.upper())},
        "HIGH_VOLATILITY": {"count": sum(1 for item in items if item.block_reason and "HIGH_VOLATILITY" in item.block_reason.upper())},
        "UNKNOWN": {"count": sum(1 for item in items if not item.block_reason or ("VOLATILITY" not in item.block_reason.upper()))},
    }
    by_momentum = {
        "BUY": {"count": sum(1 for item in items if item.signal_direction == "BUY")},
        "SELL": {"count": sum(1 for item in items if item.signal_direction == "SELL")},
        "NO_SIGNAL": {"count": sum(1 for item in items if item.signal_direction == "NO_SIGNAL")},
    }
    sample_sufficiency = {
        "observations_sufficient": len(items) >= minimum_sample,
        "signals_sufficient": signals >= max(3, minimum_sample // 10),
        "confirmations_sufficient": confirmations >= max(1, minimum_sample // 20),
        "closed_trades_sufficient": closed_positions >= max(1, minimum_sample // 25),
        "regime_coverage_sufficient": len({item.regime for item in items if item.regime}) >= 2,
    }

    return {
        "schema_version": SCHEMA_VERSION, "observations": len(items),
        "strategy_evaluations": len(items),
        "signals": signals,
        "confirmations": confirmations,
        "authorized_entries": authorized_entries,
        "opened_positions": opened_positions, "closed_positions": closed_positions,
        "directions": dict(Counter(item.signal_direction for item in items)),
        "block_reasons": dict(Counter(item.block_reason for item in items if item.block_reason)),
        "wins": len(wins), "losses": len(losses), "breakeven": sum(pnl == 0 for pnl in pnls),
        "win_rate": str(Decimal(len(wins)) / Decimal(len(pnls)) * 100) if pnls else None,
        "gross_profit": str(gross_profit), "gross_loss": str(gross_loss),
        "net_pnl": str(sum(pnls, Decimal("0"))),
        "average_pnl": str(sum(pnls, Decimal("0")) / len(pnls)) if pnls else None,
        "median_pnl": str(median(pnls)) if pnls else None,
        "average_r": str(sum(rs, Decimal("0")) / len(rs)) if rs else None,
        "median_r": str(median(rs)) if rs else None, "best_r": str(max(rs)) if rs else None,
        "worst_r": str(min(rs)) if rs else None,
        "profit_factor": str(gross_profit / gross_loss) if gross_loss else None,
        "expectancy": str(sum(pnls, Decimal("0")) / len(pnls)) if pnls else None,
        "consecutive_wins": longest_wins, "consecutive_losses": longest_losses,
        "max_drawdown": str(_maximum_drawdown(pnls)), "exit_distribution": exit_distribution,
        "by_direction": group("signal_direction"), "by_regime": group("regime"),
        "source_modes": dict(Counter(item.source_mode for item in items)),
        "stale_data_events": sum(item.block_reason == "STALE_DATA" for item in items),
        "sample_size_insufficient": len(items) < minimum_sample,
        "funnel": {
            "observations": len(items),
            "raw_signals": signals,
            "confirmation_evaluated": sum(item.confirmation_state != "NOT_EVALUATED" for item in items),
            "confirmed": confirmations,
            "risk_authorized": authorized_entries,
            "policy_admitted": authorized_entries,
            "opened": opened_positions,
            "closed": closed_positions,
            "raw_signal_rate": str(raw_signal_rate * 100) if raw_signal_rate is not None else None,
            "confirmation_rate": str(confirmation_rate * 100) if confirmation_rate is not None else None,
            "authorization_rate": str(authorization_rate * 100) if authorization_rate is not None else None,
            "entry_rate": str(entry_rate * 100) if entry_rate is not None else None,
        },
        "confidence_distribution": confidence_distribution,
        "rejection_layers": rejection_layers,
        "by_volatility": by_volatility,
        "by_momentum": by_momentum,
        "sample_sufficiency": sample_sufficiency,
    }
