"""Offline recovery of one Weltrade UNKNOWN intent; no broker mutations."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import sqlite3
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from tools import resolve_intent


@pytest.fixture
def recovery_case(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "intents.sqlite3"
    created = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
    with sqlite3.connect(db_path) as db:
        db.execute("""CREATE TABLE intent_records (
            idempotency_key TEXT PRIMARY KEY, state TEXT NOT NULL,
            broker TEXT, account_id TEXT, symbol TEXT, created_at TEXT,
            order_id TEXT, transaction_id TEXT, updated_at TEXT,
            recovery_outcome TEXT, reconciliation_state TEXT, recovery_reason TEXT
        )""")
        db.executemany(
            "INSERT INTO intent_records (idempotency_key,state,broker,account_id,symbol,created_at) "
            "VALUES (?,?,?,?,?,?)",
            [("target", "UNKNOWN", "weltrade", "4242", "SFX VOL 99", created),
             ("other", "UNKNOWN", "weltrade", "4242", "FX VOL 20", created)],
        )
    executable = tmp_path / "terminal64.exe"
    executable.touch()
    settings = SimpleNamespace(
        intent_store_path=db_path, effective_broker="weltrade",
        market_data_source="broker", weltrade_terminal_path=executable,
        effective_weltrade_login=4242, effective_weltrade_password="fixture-only",
        effective_weltrade_server="Weltrade-Demo",
    )
    terminal = MagicMock()
    terminal.initialize.return_value = True
    terminal.login.return_value = True
    terminal.account_info.return_value = SimpleNamespace(
        trade_mode=0, login=4242, server="Weltrade-Demo",
    )
    terminal.terminal_info.return_value = SimpleNamespace(
        connected=True, path=str(tmp_path),
    )
    terminal.symbol_info_tick.side_effect = lambda _symbol: SimpleNamespace(
        time=int(datetime.now(timezone.utc).timestamp()) + 3 * 3600,
    )
    terminal.positions_get.return_value = ()
    terminal.orders_get.return_value = ()
    terminal.history_orders_get.return_value = ()
    terminal.history_deals_get.return_value = ()
    monkeypatch.setattr(resolve_intent, "_supervisor_is_running", lambda: False)
    return settings, terminal


def _state(settings, key: str) -> str:
    with sqlite3.connect(settings.intent_store_path) as db:
        return db.execute(
            "SELECT state FROM intent_records WHERE idempotency_key=?", (key,),
        ).fetchone()[0]


def test_absence_requires_confirm_then_backs_up_and_audits_exact_intent(
    recovery_case, capsys,
) -> None:
    settings, terminal = recovery_case
    before = settings.intent_store_path.read_bytes()
    assert resolve_intent.main(["target"], settings=settings, terminal=terminal) == 0
    output = capsys.readouterr().out
    assert '"recommendation": "REJECTED"' in output
    assert "READ_ONLY" in output
    assert settings.intent_store_path.read_bytes() == before
    assert _state(settings, "target") == "UNKNOWN"
    terminal.order_send.assert_not_called()
    terminal.order_check.assert_not_called()

    assert resolve_intent.main(["target", "--confirm"], settings=settings, terminal=terminal) == 0
    output = capsys.readouterr().out
    assert "UNKNOWN -> REJECTED" in output
    assert _state(settings, "target") == "REJECTED"
    assert _state(settings, "other") == "UNKNOWN"
    backups = tuple((settings.intent_store_path.parent / "backups").glob("*.sqlite3"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as backup:
        assert backup.execute(
            "SELECT state FROM intent_records WHERE idempotency_key='target'"
        ).fetchone()[0] == "UNKNOWN"
        assert backup.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    with sqlite3.connect(settings.intent_store_path) as db:
        audit = db.execute(
            "SELECT actor,occurred_at,from_state,to_state,evidence_json,backup_path "
            "FROM intent_recovery_audit WHERE intent_id='target'"
        ).fetchone()
        assert audit is not None
        assert audit[0] and audit[1]
        assert audit[2:4] == ("UNKNOWN", "REJECTED")
        assert json.loads(audit[4])["historical_deals"] == []
        assert Path(audit[5]) == backups[0]
    terminal.order_send.assert_not_called()
    terminal.order_check.assert_not_called()


def test_broker_match_halts_even_with_confirm(recovery_case, capsys) -> None:
    settings, terminal = recovery_case
    terminal.history_orders_get.return_value = (
        SimpleNamespace(ticket=771, symbol="SFX Vol 99"),
    )
    assert resolve_intent.main(["target", "--confirm"], settings=settings, terminal=terminal) == 2
    output = capsys.readouterr().out
    assert '"recommendation": "HALT"' in output
    assert "771" in output
    assert _state(settings, "target") == "UNKNOWN"
    assert not (settings.intent_store_path.parent / "backups").exists()
    terminal.order_send.assert_not_called()
    terminal.order_check.assert_not_called()


def test_unreadable_history_never_recommends_rejection(recovery_case, capsys) -> None:
    settings, terminal = recovery_case
    terminal.history_deals_get.return_value = None
    assert resolve_intent.main(["target", "--confirm"], settings=settings, terminal=terminal) == 2
    assert "HALT" in capsys.readouterr().out
    assert _state(settings, "target") == "UNKNOWN"
    assert not (settings.intent_store_path.parent / "backups").exists()
