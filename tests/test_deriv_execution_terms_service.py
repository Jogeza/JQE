"""Offline end-to-end tests for durable proof consumption into typed terms."""

from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3

import pytest

from broker.deriv_execution_terms_service import (
    DerivExecutionTermsServiceRequest,
    DerivExecutionTermsServiceState,
    OfflineDerivExecutionTermsService,
)
from broker.deriv_proof_registration import (
    DerivGovernanceRevocationReason,
    DerivGovernanceRevocationTarget,
    DerivProofGovernanceRevocation,
)
from broker.deriv_proof_registry import DerivProofRegistryState
from broker.deriv_proof_store import DerivDurableProofState, SQLiteDerivProofStore
from broker.types import ExecutionQuantityUnit


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_store_fixtures = _load("jqe_service_store_fixtures", "test_deriv_proof_store.py")
_terms_fixtures = _store_fixtures._terms
_ACTIVE_AT = datetime(2026, 10, 1, tzinfo=timezone.utc)


def _persisted(tmp_path, state=None):
    path = tmp_path / "proofs.sqlite3"
    SQLiteDerivProofStore(path).persist(state or _store_fixtures._state())
    return path


def _request(state=None, **changes):
    state = state or _store_fixtures._state()
    values = {
        "applicability": state.registry.entries[0].applicability,
        "evaluated_at": _ACTIVE_AT,
        "authorized_risk_amount": Decimal("2"),
        "propositions": _terms_fixtures._propositions(),
        "account_scope": "offline:test-account",
    }
    values.update(changes)
    return DerivExecutionTermsServiceRequest(**values)


def _service(path):
    return OfflineDerivExecutionTermsService(SQLiteDerivProofStore(path))


def test_restart_to_complete_typed_terms_succeeds_offline(tmp_path) -> None:
    original = _store_fixtures._state()
    path = _persisted(tmp_path, original)
    service = _service(path)
    result = service.evaluate(_request(original))
    assert result.state is DerivExecutionTermsServiceState.TERMS_AVAILABLE
    assert result.terms is not None
    assert result.terms.stake_unit is ExecutionQuantityUnit.DERIV_STAKE
    assert result.terms.stop_loss_amount == Decimal("2")
    assert result.terms.take_profit_amount == Decimal("3")
    assert result.terms.maximum_loss == Decimal("2")
    assert result.terms.proof_id == original.registry.entries[0].proof_id
    assert result.terms.material_hash == original.registry.entries[0].candidate_material_hash


def test_valid_empty_store_returns_proof_unavailable_without_terms(tmp_path) -> None:
    service = OfflineDerivExecutionTermsService(
        SQLiteDerivProofStore(tmp_path / "empty.sqlite3")
    )
    result = service.evaluate(_request())
    assert result.state is DerivExecutionTermsServiceState.PROOF_UNAVAILABLE
    assert result.terms is None


def test_production_without_synthetic_propositions_remains_unsupported(tmp_path) -> None:
    state = _store_fixtures._state()
    result = _service(_persisted(tmp_path, state)).evaluate(
        _request(state, propositions=None)
    )
    assert result.state is DerivExecutionTermsServiceState.MODEL_UNSUPPORTED
    assert result.terms is None


def test_revoked_proof_remains_unavailable_after_restart(tmp_path) -> None:
    state = _store_fixtures._state(revoked=True)
    result = _service(_persisted(tmp_path, state)).evaluate(_request(state))
    assert result.state is DerivExecutionTermsServiceState.PROOF_REVOKED
    assert result.terms is None


@pytest.mark.parametrize(
    "evaluated_at",
    [
        datetime(2026, 8, 31, tzinfo=timezone.utc),
        datetime(2026, 12, 2, tzinfo=timezone.utc),
    ],
)
def test_pre_effective_and_expired_proofs_return_unavailable(tmp_path, evaluated_at) -> None:
    state = _store_fixtures._state()
    result = _service(_persisted(tmp_path, state)).evaluate(
        _request(state, evaluated_at=evaluated_at)
    )
    assert result.state is DerivExecutionTermsServiceState.PROOF_UNAVAILABLE
    assert result.terms is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("environment", "real"),
        ("account_currency", "OTHER"),
        ("symbol", "OTHER"),
        ("contract_family", "MULTDOWN"),
    ],
)
def test_exact_scope_mismatch_returns_no_terms(tmp_path, field, value) -> None:
    state = _store_fixtures._state()
    changed = replace(state.registry.entries[0].applicability, **{field: value})
    result = _service(_persisted(tmp_path, state)).evaluate(
        _request(state, applicability=changed)
    )
    assert result.state is DerivExecutionTermsServiceState.PROOF_UNAVAILABLE
    assert result.terms is None


def test_real_proof_does_not_match_demo_request_after_restart(tmp_path) -> None:
    original = _store_fixtures._state()
    entry = original.registry.entries[0]
    real_applicability = replace(entry.applicability, environment="real")
    assert entry.financial_semantics is not None
    real_semantics = replace(entry.financial_semantics, applicability=real_applicability)
    real_entry = replace(
        entry,
        applicability=real_applicability,
        financial_semantics=real_semantics,
        candidate_material_hash=real_semantics.material_hash,
    )
    real_state = DerivDurableProofState(DerivProofRegistryState((real_entry,)))
    result = _service(_persisted(tmp_path, real_state)).evaluate(_request(original))
    assert result.state is DerivExecutionTermsServiceState.PROOF_UNAVAILABLE


def test_maximum_loss_above_authorized_risk_returns_no_terms(tmp_path) -> None:
    state = _store_fixtures._state()
    result = _service(_persisted(tmp_path, state)).evaluate(
        _request(state, authorized_risk_amount=Decimal("1.99"))
    )
    assert result.state is DerivExecutionTermsServiceState.RISK_BOUND_EXCEEDED
    assert result.terms is None


@pytest.mark.parametrize("value", [Decimal("0"), Decimal("NaN"), Decimal("Infinity"), 2.0])
def test_authorized_risk_requires_positive_finite_decimal(value) -> None:
    with pytest.raises(ValueError, match="authorized_risk_amount"):
        _request(authorized_risk_amount=value)


def test_corrupt_store_returns_explicit_store_unavailable(tmp_path) -> None:
    state = _store_fixtures._state()
    path = _persisted(tmp_path, state)
    service = _service(path)
    with sqlite3.connect(path) as connection:
        payload = connection.execute("SELECT payload FROM deriv_proof_state").fetchone()[0]
        data = json.loads(payload)
        data["entries"][0]["candidate_material_hash"] = "sha256:" + "0" * 64
        changed = json.dumps(data, sort_keys=True, separators=(",", ":"))
        digest = "sha256:" + hashlib.sha256(changed.encode()).hexdigest()
        connection.execute(
            "UPDATE deriv_proof_state SET payload=?, payload_hash=?", (changed, digest)
        )
    result = service.evaluate(_request(state))
    assert result.state is DerivExecutionTermsServiceState.PROOF_STORE_UNAVAILABLE
    assert result.terms is None


def test_service_reloads_and_observes_new_revocation_without_stale_cache(tmp_path) -> None:
    state = _store_fixtures._state()
    path = _persisted(tmp_path, state)
    service = _service(path)
    assert service.evaluate(_request(state)).state is DerivExecutionTermsServiceState.TERMS_AVAILABLE
    entry = state.registry.entries[0]
    revocation = DerivProofGovernanceRevocation(
        schema_version=1,
        revocation_id="offline:revocation:after-first-read",
        target_kind=DerivGovernanceRevocationTarget.REGISTERED_PROOF,
        target_id=entry.proof_id,
        reason=DerivGovernanceRevocationReason.REVOKED,
        revoked_by="offline:reviewer",
        revoked_at=_ACTIVE_AT,
    )
    SQLiteDerivProofStore(path).persist(
        DerivDurableProofState(state.registry, (revocation,))
    )
    result = service.evaluate(_request(state))
    assert result.state is DerivExecutionTermsServiceState.PROOF_REVOKED
    assert result.terms is None
