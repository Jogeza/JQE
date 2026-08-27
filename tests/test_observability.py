"""Tests for safe unresolved-intent diagnostics."""

from execution.observability import log_unresolved_execution


def test_unresolved_evidence_is_allowlisted_and_structured(monkeypatch) -> None:
    captured = []
    monkeypatch.setattr("execution.observability.logger.warning", lambda message, data: captured.append(data))
    log_unresolved_execution(
        idempotency_key="key-1", state="UNKNOWN", reconciliation="AMBIGUOUS",
        order_id="contract-1", transaction_id="txn-1", error_category="TIMEOUT",
    )
    assert captured[0]["idempotency_key"] == "key-1"
    assert captured[0]["order_id"] == "contract-1"
    assert captured[0]["transaction_id"] == "txn-1"
    assert captured[0]["reconciliation"] == "AMBIGUOUS"
    assert "secret-token" not in repr(captured)


def test_logging_failure_is_swallowed(monkeypatch) -> None:
    monkeypatch.setattr("execution.observability.logger.warning", lambda *args: (_ for _ in ()).throw(RuntimeError("sink down")))
    log_unresolved_execution(idempotency_key="key-1", state="UNKNOWN")
