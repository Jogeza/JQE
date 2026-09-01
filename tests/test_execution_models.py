"""Direct contract tests for broker-neutral execution state models."""

from dataclasses import FrozenInstanceError, asdict
from inspect import signature
from typing import get_type_hints

import pytest

from execution.models import (
    ClaimState,
    IntentRecord,
    IntentRecordStatus,
    IntentRecordStore,
)


def test_intent_record_status_values_are_stable() -> None:
    assert {member.name: member.value for member in IntentRecordStatus} == {
        "PENDING": "PENDING",
        "ACCEPTED": "ACCEPTED",
        "REJECTED": "REJECTED",
        "UNKNOWN": "UNKNOWN",
    }


def test_claim_state_values_are_stable() -> None:
    assert {member.name: member.value for member in ClaimState} == {
        "CLAIMED": "CLAIMED",
        "ALREADY_EXISTS": "ALREADY_EXISTS",
        "CONFLICT": "CONFLICT",
    }


def test_intent_record_required_fields_defaults_and_equality() -> None:
    record = IntentRecord("key-1", IntentRecordStatus.PENDING)

    assert record == IntentRecord(
        idempotency_key="key-1",
        status=IntentRecordStatus.PENDING,
        order_id=None,
        transaction_id=None,
        symbol=None,
        side=None,
        quantity=None,
        entry=None,
        stop_loss=None,
        take_profit=None,
        authorized_risk_amount=None,
        expected_loss_at_stop=None,
        broker=None,
        account_id=None,
    )
    assert asdict(record) == {
        "idempotency_key": "key-1",
        "status": IntentRecordStatus.PENDING,
        "order_id": None,
        "transaction_id": None,
        "symbol": None,
        "side": None,
        "quantity": None,
        "entry": None,
        "stop_loss": None,
        "take_profit": None,
        "authorized_risk_amount": None,
        "expected_loss_at_stop": None,
        "broker": None,
        "account_id": None,
    }


def test_intent_record_preserves_optional_broker_identity_evidence() -> None:
    record = IntentRecord(
        "key-1",
        IntentRecordStatus.ACCEPTED,
        order_id="order-7",
        transaction_id="transaction-9",
    )

    assert record.order_id == "order-7"
    assert record.transaction_id == "transaction-9"


def test_intent_record_is_frozen_and_slotted() -> None:
    record = IntentRecord("key-1", IntentRecordStatus.PENDING)

    with pytest.raises(FrozenInstanceError):
        record.status = IntentRecordStatus.ACCEPTED  # type: ignore[misc]
    assert not hasattr(record, "__dict__")
    assert IntentRecord.__slots__ == (
        "idempotency_key",
        "status",
        "order_id",
        "transaction_id",
        "symbol",
        "side",
        "quantity",
        "entry",
        "stop_loss",
        "take_profit",
        "authorized_risk_amount",
        "expected_loss_at_stop",
        "broker",
        "account_id",
    )


def test_intent_record_store_declares_expected_protocol_contract() -> None:
    assert get_type_hints(IntentRecordStore) == {"recovery_mode": bool}
    assert list(signature(IntentRecordStore.get).parameters) == [
        "self",
        "idempotency_key",
    ]
    assert get_type_hints(IntentRecordStore.get) == {
        "idempotency_key": str,
        "return": IntentRecord | None,
    }
    assert list(signature(IntentRecordStore.try_claim).parameters) == ["self", "record"]
    assert get_type_hints(IntentRecordStore.try_claim) == {
        "record": IntentRecord,
        "return": ClaimState,
    }
    assert list(signature(IntentRecordStore.transition).parameters) == ["self", "record"]
    assert get_type_hints(IntentRecordStore.transition) == {
        "record": IntentRecord,
        "return": bool,
    }


def test_intent_record_from_and_to_execution_intent() -> None:
    from broker.types import ExecutionQuantity, ExecutionQuantityUnit, OrderSide
    from execution.policy import ExecutionIntent

    intent = ExecutionIntent(
        symbol="EURUSD",
        side=OrderSide.BUY,
        quantity=ExecutionQuantity(value=2.5, unit=ExecutionQuantityUnit.SIMULATION_UNITS),
        authorized_risk_amount=50.0,
        expected_loss_at_stop=48.0,
        quantity_risk_verified=True,
        entry=1.1000,
        stop_loss=1.0950,
        take_profit=1.1100,
        idempotency_key="idemp-eurusd-01",
        risk_approved=True,
    )
    record = IntentRecord.from_execution_intent(
        intent,
        status=IntentRecordStatus.PENDING,
        broker="simulation",
        account_id="acct-sim",
    )
    assert record.idempotency_key == "idemp-eurusd-01"
    assert record.symbol == "EURUSD"
    assert record.side is OrderSide.BUY
    assert record.quantity == ExecutionQuantity(value=2.5, unit=ExecutionQuantityUnit.SIMULATION_UNITS)
    assert record.entry == 1.1000
    assert record.stop_loss == 1.0950
    assert record.take_profit == 1.1100
    assert record.authorized_risk_amount == 50.0
    assert record.expected_loss_at_stop == 48.0
    assert record.broker == "simulation"
    assert record.account_id == "acct-sim"

    reconstructed = record.to_execution_intent()
    assert reconstructed == intent


def test_intent_record_to_execution_intent_returns_none_if_incomplete() -> None:
    record = IntentRecord("key-partial", IntentRecordStatus.PENDING, symbol="EURUSD")
    assert record.to_execution_intent() is None
