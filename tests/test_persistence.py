"""Tests for durable intent persistence semantics."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import multiprocessing
import sqlite3
import time

from execution.models import ClaimState, IntentRecord, IntentRecordStatus
from execution.persistence import SQLiteIntentRecordStore
import pytest


def _record(status: IntentRecordStatus = IntentRecordStatus.PENDING) -> IntentRecord:
    return IntentRecord("key-1", status)


def test_lookup_and_restart_persistence(tmp_path) -> None:
    path = tmp_path / "intents.sqlite3"
    first = SQLiteIntentRecordStore(path)
    assert first.get("key-1") is None
    assert first.try_claim(_record()) is ClaimState.CLAIMED

    restarted = SQLiteIntentRecordStore(path)
    assert restarted.get("key-1") == _record()


def test_idempotency_identity_round_trips_unchanged(tmp_path) -> None:
    store = SQLiteIntentRecordStore(tmp_path / "intents.sqlite3")
    record = IntentRecord("JQE-intent-α/01", IntentRecordStatus.PENDING)
    assert store.try_claim(record) is ClaimState.CLAIMED
    assert store.get(record.idempotency_key) == record


def test_broker_identity_evidence_round_trips(tmp_path) -> None:
    store = SQLiteIntentRecordStore(tmp_path / "intents.sqlite3")
    record = IntentRecord("key-evidence", IntentRecordStatus.UNKNOWN, "order-7", "txn-9")
    assert store.try_claim(record) is ClaimState.CLAIMED
    assert store.get(record.idempotency_key) == record
    inspected = store.inspect(record.idempotency_key)
    assert inspected is not None
    assert inspected.order_id == "order-7"
    assert inspected.transaction_id == "txn-9"


def test_blank_identity_is_rejected(tmp_path) -> None:
    store = SQLiteIntentRecordStore(tmp_path / "intents.sqlite3")
    with pytest.raises(ValueError):
        store.try_claim(IntentRecord("  ", IntentRecordStatus.PENDING))


def test_operational_inspection_is_read_only(tmp_path) -> None:
    store = SQLiteIntentRecordStore(tmp_path / "nested" / "intents.sqlite3")
    record = _record()
    assert store.try_claim(record) is ClaimState.CLAIMED
    inspected = store.inspect(record.idempotency_key)
    assert inspected is not None
    assert inspected.status is IntentRecordStatus.PENDING
    assert inspected.order_id is None
    assert inspected.created_at
    assert inspected.updated_at
    assert store.get(record.idempotency_key) == record


def test_database_read_failure_fails_closed(tmp_path, monkeypatch) -> None:
    store = SQLiteIntentRecordStore(tmp_path / "intents.sqlite3")
    monkeypatch.setattr(store, "_connect", lambda: (_ for _ in ()).throw(OSError("unavailable")))
    with pytest.raises(OSError):
        store.get("key-1")


def _process_claim(path: str, queue) -> None:
    store = SQLiteIntentRecordStore(path)
    queue.put(store.try_claim(_record()).value)


def test_process_level_atomic_claim(tmp_path) -> None:
    path = str(tmp_path / "process.sqlite3")
    SQLiteIntentRecordStore(path)
    context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    processes = [context.Process(target=_process_claim, args=(path, queue)) for _ in range(2)]
    for process in processes:
        process.start()
    results = [queue.get(timeout=10) for _ in processes]
    for process in processes:
        process.join(timeout=10)
    assert sorted(results) == ["ALREADY_EXISTS", "CLAIMED"]


def test_corrupt_database_is_not_interpreted_as_empty(tmp_path) -> None:
    path = tmp_path / "corrupt.sqlite3"
    path.write_bytes(b"not a sqlite database")
    store = SQLiteIntentRecordStore.__new__(SQLiteIntentRecordStore)
    store._path = str(path)
    with pytest.raises(sqlite3.DatabaseError):
        store.get("key-1")


def test_write_lock_exceeding_busy_timeout_fails(tmp_path) -> None:
    path = tmp_path / "locked.sqlite3"
    SQLiteIntentRecordStore(path)
    lock = sqlite3.connect(path)
    lock.execute("BEGIN IMMEDIATE")
    try:
        started = time.monotonic()
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            SQLiteIntentRecordStore(path).try_claim(_record())
        assert time.monotonic() - started >= 4.5
    finally:
        lock.rollback()
        lock.close()


def test_backup_restore_preserves_intents_and_stale_restore_is_fail_closed(tmp_path) -> None:
    live_path = tmp_path / "live.sqlite3"
    store = SQLiteIntentRecordStore(live_path)
    for status, key in ((IntentRecordStatus.PENDING, "pending"), (IntentRecordStatus.UNKNOWN, "unknown"), (IntentRecordStatus.ACCEPTED, "accepted"), (IntentRecordStatus.REJECTED, "rejected")):
        record = IntentRecord(key, status)
        assert store.try_claim(record) is ClaimState.CLAIMED
    backup = tmp_path / "backup.sqlite3"
    store.backup_to(backup)
    assert SQLiteIntentRecordStore(backup).inspect("unknown") is not None
    assert store.try_claim(IntentRecord("newer", IntentRecordStatus.UNKNOWN)) is ClaimState.CLAIMED
    restored = SQLiteIntentRecordStore(backup, recovery_mode=True)
    assert restored.inspect("pending").status is IntentRecordStatus.PENDING
    assert restored.inspect("unknown").status is IntentRecordStatus.UNKNOWN
    assert restored.inspect("accepted").status is IntentRecordStatus.ACCEPTED
    assert restored.inspect("rejected").status is IntentRecordStatus.REJECTED
    assert restored.inspect("newer") is None


def test_atomic_duplicate_claim(tmp_path) -> None:
    store = SQLiteIntentRecordStore(tmp_path / "intents.sqlite3")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: store.try_claim(_record()), range(2)))
    assert sorted(result.value for result in results) == ["ALREADY_EXISTS", "CLAIMED"]


def test_legal_transitions_and_terminal_regression_protection(tmp_path) -> None:
    store = SQLiteIntentRecordStore(tmp_path / "intents.sqlite3")
    assert store.try_claim(_record()) is ClaimState.CLAIMED
    assert store.transition(_record(IntentRecordStatus.UNKNOWN)) is True
    assert store.transition(_record(IntentRecordStatus.ACCEPTED)) is True
    assert store.transition(_record(IntentRecordStatus.PENDING)) is False
    assert store.transition(_record(IntentRecordStatus.REJECTED)) is False


def test_missing_transition_is_safe(tmp_path) -> None:
    store = SQLiteIntentRecordStore(tmp_path / "intents.sqlite3")
    assert store.transition(_record(IntentRecordStatus.ACCEPTED)) is False
