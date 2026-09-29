"""Read-only by default, narrowly resolve one Weltrade demo UNKNOWN intent.

The command never submits, modifies, or closes a broker order.  A confirmed
absence still requires --confirm; matching or unreadable broker evidence halts.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import getpass
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

import MetaTrader5 as mt5

from broker.demo_guard import MT5_ACCOUNT_TRADE_MODE_DEMO
from broker.mt5_gateway import _history_server_offset
from broker.scope import enforce_weltrade_only
from config.settings import Settings
from core.processes import is_process_alive


_HISTORY_CHUNK = timedelta(hours=1)
_WINDOW_MARGIN = timedelta(minutes=10)
_MAX_CHUNK_RECORDS = 1000
_HEARTBEAT = Path("state/weltrade_execution_supervisor_heartbeat.json")


@dataclass(frozen=True)
class RecoveryFinding:
    intent_id: str
    state: str
    symbol: str
    created_at: str
    observed_at: str
    window_start: str
    window_end: str
    server_utc_offset_seconds: int | None
    positions: tuple[str, ...]
    pending_orders: tuple[str, ...]
    historical_orders: tuple[str, ...]
    historical_deals: tuple[str, ...]
    recommendation: str
    reason: str

    def evidence(self) -> dict[str, object]:
        return {
            "symbol": self.symbol, "created_at": self.created_at,
            "observed_at": self.observed_at,
            "window_start": self.window_start, "window_end": self.window_end,
            "server_utc_offset_seconds": self.server_utc_offset_seconds,
            "positions": self.positions, "pending_orders": self.pending_orders,
            "historical_orders": self.historical_orders,
            "historical_deals": self.historical_deals,
            "recommendation": self.recommendation, "reason": self.reason,
        }


def _read_intent(path: Path, intent_id: str) -> sqlite3.Row:
    if not path.is_file():
        raise RuntimeError("Intent store is unavailable")
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        row = db.execute(
            "SELECT idempotency_key, state, broker, account_id, symbol, "
            "created_at, order_id, transaction_id FROM intent_records "
            "WHERE idempotency_key=?", (intent_id,),
        ).fetchone()
    if row is None:
        raise RuntimeError("Exact intent ID was not found")
    if row["state"] != "UNKNOWN" or row["broker"] != "weltrade":
        raise RuntimeError("Intent is not an unresolved Weltrade UNKNOWN intent")
    if row["order_id"] or row["transaction_id"]:
        raise RuntimeError("Intent has a broker identifier; human reconciliation is required")
    if not row["symbol"] or not row["account_id"]:
        raise RuntimeError("Intent identity is incomplete")
    return row


def _supervisor_is_running(path: Path = _HEARTBEAT) -> bool:
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("status") != "STOPPED" and is_process_alive(data.get("pid"))
    except (OSError, ValueError, TypeError):
        return True


def _history(terminal: object, method: str, start: datetime, end: datetime) -> tuple[object, ...]:
    records: dict[str, object] = {}
    cursor = start
    while cursor < end:
        next_end = min(cursor + _HISTORY_CHUNK, end)
        part = getattr(terminal, method)(cursor, next_end)
        if part is None or len(part) >= _MAX_CHUNK_RECORDS:
            raise RuntimeError(f"{method} returned unavailable or possibly truncated history")
        for item in part:
            ticket = getattr(item, "ticket", None)
            if ticket is None:
                raise RuntimeError(f"{method} returned a record without a ticket")
            records[str(ticket)] = item
        cursor = next_end
    return tuple(records.values())


def inspect_intent(
    intent_id: str, settings: Settings, *, terminal: object = mt5,
    now: datetime | None = None,
) -> RecoveryFinding:
    """Read one intent and all potentially matching demo broker evidence."""
    if _supervisor_is_running():
        raise RuntimeError("Execution supervisor may be running; recovery is blocked")
    enforce_weltrade_only(
        broker=settings.effective_broker,
        market_data_source=settings.market_data_source,
    )
    row = _read_intent(Path(settings.intent_store_path), intent_id)
    observed = now or datetime.now(timezone.utc)
    created = datetime.fromisoformat(row["created_at"])
    if created.tzinfo is None or observed.tzinfo is None or created > observed:
        raise RuntimeError("Intent time window is invalid")
    start = created.astimezone(timezone.utc) - _WINDOW_MARGIN
    end = observed.astimezone(timezone.utc)
    path = settings.weltrade_terminal_path
    login = settings.effective_weltrade_login
    server = settings.effective_weltrade_server
    password = settings.effective_weltrade_password
    if path is None or not Path(path).is_file() or not login or not server or not password:
        raise RuntimeError("Weltrade demo configuration is incomplete")
    connected = False
    try:
        connected = terminal.initialize(str(Path(path).resolve())) is True
        if not connected or terminal.login(login, password=password, server=server) is not True:
            raise RuntimeError("Weltrade demo connection failed")
        account = terminal.account_info()
        info = terminal.terminal_info()
        if account is None or info is None or getattr(info, "connected", False) is not True:
            raise RuntimeError("Weltrade demo connection is unreadable")
        # DemoOnlyGuard records evidence as a side effect.  Mirror its strict
        # trade_mode check here so the default command remains genuinely read-only.
        trade_mode = getattr(account, "trade_mode", None)
        if type(trade_mode) is not int or trade_mode != MT5_ACCOUNT_TRADE_MODE_DEMO:
            raise RuntimeError("Weltrade account is not authoritatively DEMO")
        if (getattr(account, "login", None) != login
                or str(getattr(account, "login", "")) != row["account_id"]
                or getattr(account, "server", None) != server
                or "WELTRADE" not in str(server).upper()
                or Path(str(getattr(info, "path", ""))).resolve() != Path(path).resolve().parent):
            raise RuntimeError("Weltrade demo account or terminal identity mismatch")
        offset = _history_server_offset(terminal, end)
        if offset is None:
            raise RuntimeError("Weltrade server-to-UTC offset is unresolved")
        positions = terminal.positions_get()
        pending = terminal.orders_get()
        if positions is None or pending is None:
            raise RuntimeError("Current broker positions or orders are unreadable")
        historical_orders = _history(terminal, "history_orders_get", start, end)
        historical_deals = _history(terminal, "history_deals_get", start, end)
        symbol = row["symbol"].strip().upper()
        ids = lambda records: tuple(sorted(
            str(item.ticket) for item in records
            if str(getattr(item, "symbol", "")).strip().upper() == symbol
        ))
        matching_positions = tuple(sorted(
            str(item.ticket) for item in positions
            if str(getattr(item, "symbol", "")).strip().upper() == symbol
        ))
        found = (
            matching_positions, ids(pending),
            ids(historical_orders), ids(historical_deals),
        )
        match = any(found)
        return RecoveryFinding(
            intent_id=intent_id, state=row["state"], symbol=symbol,
            created_at=row["created_at"], observed_at=end.isoformat(),
            window_start=start.isoformat(), window_end=end.isoformat(),
            server_utc_offset_seconds=offset,
            positions=found[0], pending_orders=found[1],
            historical_orders=found[2], historical_deals=found[3],
            recommendation="HALT" if match else "REJECTED",
            reason=("Same-symbol broker evidence requires human reconciliation"
                    if match else "No matching broker position, pending order, historical order, or deal"),
        )
    finally:
        if connected:
            terminal.shutdown()


def _backup_before_write(source: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    destination = backup_dir / (
        f"{source.stem}-pre-recovery-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid4().hex[:8]}.sqlite3"
    )
    with sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True) as original:
        with sqlite3.connect(destination) as backup:
            original.backup(backup)
            if backup.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("Intent database backup failed integrity check")
    if not destination.is_file() or destination.stat().st_size == 0:
        raise RuntimeError("Intent database backup is missing")
    return destination


def confirm_resolution(
    finding: RecoveryFinding, settings: Settings, *, backup_dir: Path | None = None,
) -> Path:
    """Atomically resolve only the inspected ID and write its audit record."""
    if finding.recommendation != "REJECTED" or any((
        finding.positions, finding.pending_orders,
        finding.historical_orders, finding.historical_deals,
    )):
        raise RuntimeError("Broker evidence is ambiguous; resolution is refused")
    if _supervisor_is_running():
        raise RuntimeError("Execution supervisor may be running; recovery is blocked")
    source = Path(settings.intent_store_path).resolve()
    backup = _backup_before_write(source, backup_dir or source.parent / "backups")
    actor = getpass.getuser()
    at = datetime.now(timezone.utc).isoformat()
    evidence = json.dumps(finding.evidence(), sort_keys=True)
    with sqlite3.connect(source, timeout=5) as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT state, broker, symbol, created_at, order_id, transaction_id "
            "FROM intent_records WHERE idempotency_key=?", (finding.intent_id,),
        ).fetchone()
        if row != ("UNKNOWN", "weltrade", finding.symbol, finding.created_at, None, None):
            raise RuntimeError("Exact intent changed since inspection; no transition written")
        db.execute("""CREATE TABLE IF NOT EXISTS intent_recovery_audit (
            audit_id TEXT PRIMARY KEY, intent_id TEXT NOT NULL,
            actor TEXT NOT NULL, occurred_at TEXT NOT NULL,
            from_state TEXT NOT NULL, to_state TEXT NOT NULL,
            evidence_json TEXT NOT NULL, backup_path TEXT NOT NULL
        )""")
        updated = db.execute(
            "UPDATE intent_records SET state='REJECTED', updated_at=?, "
            "recovery_outcome='OPERATOR_CONFIRMED_ABSENCE', "
            "reconciliation_state='CONFIRMED_ABSENCE', "
            "recovery_reason=? "
            "WHERE idempotency_key=? AND state='UNKNOWN' AND order_id IS NULL "
            "AND transaction_id IS NULL",
            (at, finding.reason, finding.intent_id),
        ).rowcount
        if updated != 1:
            raise RuntimeError("Exact intent transition failed; no audit committed")
        db.execute(
            "INSERT INTO intent_recovery_audit VALUES (?,?,?,?,?,?,?,?)",
            (uuid4().hex, finding.intent_id, actor, at, "UNKNOWN", "REJECTED", evidence, str(backup)),
        )
    return backup


def main(argv: list[str] | None = None, *, settings: Settings | None = None,
         terminal: object = mt5) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("intent_id", help="Exact durable intent idempotency key")
    parser.add_argument("--confirm", action="store_true", help="Write this one verified transition")
    args = parser.parse_args(argv)
    try:
        configured = settings or Settings()
        finding = inspect_intent(args.intent_id, configured, terminal=terminal)
        print(json.dumps(finding.evidence() | {
            "intent_id": finding.intent_id, "state": finding.state,
        }, sort_keys=True))
        if not args.confirm:
            print("READ_ONLY: no state changed; --confirm is required for a transition")
            return 0
        if finding.recommendation != "REJECTED":
            print("HALT: matching broker evidence found; no state changed")
            return 2
        backup = confirm_resolution(finding, configured)
        print(json.dumps({"transition": "UNKNOWN -> REJECTED", "intent_id": finding.intent_id,
                          "backup": str(backup), "audit": "intent_recovery_audit"}))
        return 0
    except Exception as exc:
        # Exception text from MT5/settings can contain operator details.
        print(f"HALT: recovery refused ({type(exc).__name__}); no transition confirmed")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
