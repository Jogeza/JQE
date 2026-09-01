"""Read-only API diagnostics for durable startup recovery state."""

from __future__ import annotations

import sqlite3
from unittest.mock import AsyncMock, patch

import pytest

from api.app import create_app
from api.routes import get_recovery_diagnostics
from api.service import ApplicationService
from broker.types import ExecutionQuantity, ExecutionQuantityUnit, OrderSide
from config.settings import settings
from execution.models import ClaimState, IntentRecord, IntentRecordStatus
from execution.persistence import SQLiteIntentRecordStore


def _record(key: str, status: IntentRecordStatus, **changes) -> IntentRecord:
    values = dict(
        idempotency_key=key,
        status=status,
        order_id="SIM-1",
        transaction_id="TX-1",
        symbol="XAUUSD",
        side=OrderSide.BUY,
        quantity=ExecutionQuantity(
            value=1.25, unit=ExecutionQuantityUnit.SIMULATION_UNITS
        ),
        entry=100.0,
        stop_loss=99.0,
        take_profit=102.0,
        authorized_risk_amount=10.0,
        expected_loss_at_stop=9.5,
        broker="simulation",
        account_id="SIMULATED",
    )
    values.update(changes)
    return IntentRecord(**values)


@pytest.fixture
def diagnostic_store(tmp_path, monkeypatch):
    path = tmp_path / "intents.sqlite3"
    monkeypatch.setattr(settings, "intent_store_path", path)
    monkeypatch.setattr(settings, "broker", "simulation")
    return SQLiteIntentRecordStore(path)


def test_zero_unresolved_intents_is_clear(diagnostic_store) -> None:
    response = ApplicationService().get_recovery_diagnostics()
    assert response.status == "CLEAR"
    assert response.execution_blocked is False
    assert response.unresolved_intent_count == 0
    assert response.intents == []


@pytest.mark.parametrize("status", [IntentRecordStatus.PENDING, IntentRecordStatus.UNKNOWN])
def test_unresolved_intent_preserves_typed_operator_fields(
    diagnostic_store, status
) -> None:
    assert diagnostic_store.try_claim(_record("key-1", status)) is ClaimState.CLAIMED
    response = ApplicationService().get_recovery_diagnostics()
    item = response.intents[0]
    assert response.status == "BLOCKED"
    assert response.execution_blocked is True
    assert item.intent_state == status.value
    assert item.quantity is not None
    assert item.quantity.value == 1.25
    assert item.quantity.unit == "SIMULATION_UNITS"
    assert (item.broker, item.account_id, item.symbol, item.side) == (
        "simulation", "SIMULATED", "XAUUSD", "BUY"
    )
    assert item.created_at and item.updated_at
    assert item.order_id == "SIM-1"
    assert item.transaction_id == "TX-1"


def test_multiple_unresolved_intents_are_enumerated(diagnostic_store) -> None:
    for key, status in (("one", IntentRecordStatus.PENDING), ("two", IntentRecordStatus.UNKNOWN)):
        assert diagnostic_store.try_claim(_record(key, status)) is ClaimState.CLAIMED
    response = ApplicationService().get_recovery_diagnostics()
    assert response.unresolved_intent_count == 2
    assert [item.idempotency_key for item in response.intents] == ["one", "two"]


def test_malformed_payload_and_scope_mismatch_are_explicit(diagnostic_store) -> None:
    assert diagnostic_store.try_claim(
        IntentRecord("malformed", IntentRecordStatus.PENDING)
    ) is ClaimState.CLAIMED
    assert diagnostic_store.try_claim(
        _record("wrong-scope", IntentRecordStatus.UNKNOWN, account_id="OTHER")
    ) is ClaimState.CLAIMED
    response = ApplicationService().get_recovery_diagnostics()
    assert [item.recovery_outcome for item in response.intents] == [
        "MALFORMED_RECORD", "SCOPE_MISMATCH"
    ]
    assert response.execution_blocked is True


@pytest.mark.parametrize(
    "outcome,classification,reason",
    [
        ("REMAINS_UNKNOWN", "AMBIGUOUS", "Broker evidence is ambiguous"),
        ("RECONCILIATION_UNAVAILABLE", "UNAVAILABLE", "Broker state unavailable"),
        ("RECONCILIATION_ERROR", "ERROR", "Recovery reconciliation failed"),
    ],
)
def test_durable_recovery_classification_is_reported(
    diagnostic_store, outcome, classification, reason
) -> None:
    assert diagnostic_store.try_claim(
        _record("key", IntentRecordStatus.UNKNOWN)
    ) is ClaimState.CLAIMED
    assert diagnostic_store.record_recovery_diagnostic(
        "key",
        recovery_outcome=outcome,
        reconciliation_state=classification,
        recovery_reason=reason,
    )
    item = ApplicationService().get_recovery_diagnostics().intents[0]
    assert item.recovery_outcome == outcome
    assert item.reconciliation_classification == classification
    assert item.blocking_reason == reason


def test_repeated_get_is_read_only_and_never_contacts_execution_boundaries(
    diagnostic_store,
) -> None:
    assert diagnostic_store.try_claim(
        _record("key", IntentRecordStatus.UNKNOWN)
    ) is ClaimState.CLAIMED
    before = diagnostic_store.inspect("key")
    service = ApplicationService(gateway=AsyncMock())
    with patch("api.service.get_gateway") as get_gateway, patch(
        "execution.recovery.StartupRecoveryService.recover", new_callable=AsyncMock
    ) as reconcile:
        first = get_recovery_diagnostics(service=service)
        second = get_recovery_diagnostics(service=service)
    assert first == second
    assert diagnostic_store.inspect("key") == before
    get_gateway.assert_not_called()
    reconcile.assert_not_awaited()
    service._gateway.submit_order.assert_not_awaited()


def test_read_failure_is_unknown_and_blocked(tmp_path, monkeypatch) -> None:
    path = tmp_path / "broken.sqlite3"
    path.write_bytes(b"not sqlite")
    monkeypatch.setattr(settings, "intent_store_path", path)
    response = ApplicationService().get_recovery_diagnostics()
    assert response.status == "UNKNOWN"
    assert response.execution_blocked is True
    assert response.intents == []


def test_response_allowlist_does_not_expose_credentials(diagnostic_store) -> None:
    assert diagnostic_store.try_claim(
        _record("key", IntentRecordStatus.UNKNOWN)
    ) is ClaimState.CLAIMED
    payload = ApplicationService().get_recovery_diagnostics().model_dump_json().lower()
    for forbidden in ("token", "password", "authorization", "credential", "secret"):
        assert forbidden not in payload


def test_openapi_exposes_get_only_typed_recovery_contract() -> None:
    operations = create_app().openapi()["paths"]["/api/v1/execution/recovery"]
    assert set(operations) == {"get"}
    schema = create_app().openapi()["components"]["schemas"]
    assert "RecoveryDiagnosticsResponse" in schema
    assert "RecoveryQuantityDTO" in schema


def test_missing_store_is_unknown_without_creating_database(tmp_path, monkeypatch) -> None:
    path = tmp_path / "missing.sqlite3"
    monkeypatch.setattr(settings, "intent_store_path", path)
    response = ApplicationService().get_recovery_diagnostics()
    assert response.status == "UNKNOWN"
    assert response.execution_blocked is True
    assert not path.exists()
