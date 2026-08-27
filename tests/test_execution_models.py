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
    )
    assert asdict(record) == {
        "idempotency_key": "key-1",
        "status": IntentRecordStatus.PENDING,
        "order_id": None,
        "transaction_id": None,
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
