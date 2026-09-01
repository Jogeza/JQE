"""Offline restart and corruption tests for the durable Deriv proof store."""

from dataclasses import replace
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sqlite3

import pytest

from broker.deriv_proof_consumption import (
    DerivProofConsumptionReason,
    DerivProofConsumptionRequest,
    DerivProofConsumptionState,
    validate_authoritative_proof_for_capability,
)
from broker.deriv_proof_registration import (
    DerivGovernanceRevocationReason,
    DerivGovernanceRevocationTarget,
    DerivProofGovernanceRevocation,
)
from broker.deriv_proof_registry import DerivProofRegistryState
from broker.deriv_proof_store import (
    DERIV_PROOF_STORE_SCHEMA_VERSION,
    DerivDurableProofState,
    DerivProofStoreError,
    SQLiteDerivProofStore,
)


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_terms = _load("jqe_store_terms_fixtures", "test_deriv_execution_terms.py")
_ACTIVE_AT = datetime(2026, 10, 1, tzinfo=timezone.utc)


def _state(*, revoked: bool = False) -> DerivDurableProofState:
    proof, _ = _terms._consumed_proof()
    assert proof.entry is not None
    revocations = ()
    if revoked:
        revocations = (
            DerivProofGovernanceRevocation(
                schema_version=1,
                revocation_id="offline:revocation:R1",
                target_kind=DerivGovernanceRevocationTarget.REGISTERED_PROOF,
                target_id=proof.entry.proof_id,
                reason=DerivGovernanceRevocationReason.REVOKED,
                revoked_by="offline:reviewer",
                revoked_at=_ACTIVE_AT,
            ),
        )
    return DerivDurableProofState(DerivProofRegistryState((proof.entry,)), revocations)


def _request(state: DerivDurableProofState, evaluated_at: datetime = _ACTIVE_AT, **changes):
    entry = state.registry.entries[0]
    values = {
        "schema_version": 1,
        "proof_id": entry.proof_id,
        "admission_id": entry.admission_id,
        "candidate_id": entry.candidate_id,
        "candidate_material_hash": entry.candidate_material_hash,
        "verification_decision_id": entry.verification_decision_id,
        "source_assessment_id": entry.source_assessment_id,
        "review_decision_id": entry.review_decision_id,
        "artifact_ids": entry.artifact_ids,
        "artifact_content_hashes": entry.artifact_content_hashes,
        "claim_ids": entry.claim_ids,
        "applicability": entry.applicability,
        "loss_model_id": entry.loss_model_id,
        "loss_model_version": entry.loss_model_version,
        "evidence_source_id": entry.evidence_source_id,
        "valid_from": entry.valid_from,
        "valid_until": entry.valid_until,
        "evaluated_at": evaluated_at,
        "financial_semantics": entry.financial_semantics,
    }
    values.update(changes)
    return DerivProofConsumptionRequest(**values)


def _consume(state: DerivDurableProofState, request: DerivProofConsumptionRequest):
    return validate_authoritative_proof_for_capability(
        state.registry, request, state.revocations
    )


def test_new_store_is_empty_valid_and_does_not_create_authority(tmp_path) -> None:
    store = SQLiteDerivProofStore(tmp_path / "proofs.sqlite3")
    loaded = store.load()
    assert loaded == DerivDurableProofState()
    assert loaded.registry.entries == ()
    with sqlite3.connect(tmp_path / "proofs.sqlite3") as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute("PRAGMA synchronous").fetchone()[0] == 2


def test_complete_state_round_trips_and_consumes_after_restart(tmp_path) -> None:
    path = tmp_path / "proofs.sqlite3"
    original = _state()
    SQLiteDerivProofStore(path).persist(original)
    loaded = SQLiteDerivProofStore(path).load()
    assert loaded == original
    result = _consume(loaded, _request(loaded))
    assert result.state is DerivProofConsumptionState.PROOF_AVAILABLE


def test_persisting_exact_state_twice_is_idempotent(tmp_path) -> None:
    store = SQLiteDerivProofStore(tmp_path / "proofs.sqlite3")
    original = _state()
    assert store.persist(original) == original
    assert store.persist(original) == original
    with sqlite3.connect(tmp_path / "proofs.sqlite3") as connection:
        assert connection.execute("SELECT count(*) FROM deriv_proof_state").fetchone()[0] == 1


def test_existing_authority_cannot_be_altered_or_removed(tmp_path) -> None:
    store = SQLiteDerivProofStore(tmp_path / "proofs.sqlite3")
    original = _state()
    store.persist(original)
    entry = original.registry.entries[0]
    altered = DerivDurableProofState(DerivProofRegistryState((replace(entry, admitted_by="other"),)))
    with pytest.raises(DerivProofStoreError, match="altered or removed"):
        store.persist(altered)
    with pytest.raises(DerivProofStoreError, match="altered or removed"):
        store.persist(DerivDurableProofState())
    assert store.load() == original


def test_duplicate_proof_identity_with_conflicting_authority_is_rejected() -> None:
    entry = _state().registry.entries[0]
    conflicting = replace(
        entry,
        admission_id="offline:admission:conflict",
        candidate_id="offline:candidate:conflict",
    )
    with pytest.raises(ValueError, match="duplicate proof ID"):
        DerivProofRegistryState((entry, conflicting))


def test_multiple_proofs_preserve_deterministic_lookup_identity(tmp_path) -> None:
    first = _state().registry.entries[0]
    second = replace(
        first,
        proof_id="offline:proof:Z2",
        admission_id="offline:admission:Z2",
        candidate_id="offline:candidate:Z2",
    )
    state = DerivDurableProofState(DerivProofRegistryState(tuple(sorted((second, first), key=lambda item: item.proof_id))))
    store = SQLiteDerivProofStore(tmp_path / "proofs.sqlite3")
    loaded = store.persist(state)
    assert tuple(item.proof_id for item in loaded.registry.entries) == tuple(sorted((first.proof_id, second.proof_id)))
    assert loaded.registry.get_historical(first.proof_id) == first
    assert loaded.registry.get_historical(second.proof_id) == second
    assert loaded.registry.get_historical("offline:missing") is None


@pytest.mark.parametrize(
    "evaluated_at,expected",
    [
        (datetime(2026, 8, 31, tzinfo=timezone.utc), DerivProofConsumptionReason.PROOF_NOT_YET_EFFECTIVE),
        (_ACTIVE_AT, DerivProofConsumptionReason.EXACT_ACTIVE_PROOF),
        (datetime(2026, 12, 2, tzinfo=timezone.utc), DerivProofConsumptionReason.PROOF_EXPIRED),
    ],
)
def test_validity_window_is_enforced_after_reload(tmp_path, evaluated_at, expected) -> None:
    store = SQLiteDerivProofStore(tmp_path / "proofs.sqlite3")
    store.persist(_state())
    loaded = SQLiteDerivProofStore(tmp_path / "proofs.sqlite3").load()
    result = _consume(loaded, _request(loaded, evaluated_at))
    assert expected in result.reason_codes


@pytest.mark.parametrize(
    "field,value",
    [
        ("environment", "real"),
        ("account_currency", "OTHER"),
        ("symbol", "OTHER"),
        ("contract_family", "MULTDOWN"),
    ],
)
def test_exact_scope_is_preserved_after_reload(tmp_path, field, value) -> None:
    store = SQLiteDerivProofStore(tmp_path / "proofs.sqlite3")
    store.persist(_state())
    loaded = store.load()
    applicability = replace(loaded.registry.entries[0].applicability, **{field: value})
    result = _consume(
        loaded,
        _request(loaded, applicability=applicability, financial_semantics=None),
    )
    assert result.state is DerivProofConsumptionState.PROOF_UNAVAILABLE
    assert result.reason_codes == frozenset({DerivProofConsumptionReason.APPLICABILITY_MISMATCH})


def test_revocation_survives_restart_and_remains_unusable(tmp_path) -> None:
    path = tmp_path / "proofs.sqlite3"
    SQLiteDerivProofStore(path).persist(_state(revoked=True))
    loaded = SQLiteDerivProofStore(path).load()
    result = _consume(loaded, _request(loaded))
    assert result.state is DerivProofConsumptionState.PROOF_REVOKED
    assert DerivProofConsumptionReason.PROOF_REVOKED in result.reason_codes


@pytest.mark.parametrize(
    "mutation",
    ["malformed-json", "hash-mismatch", "invalid-timestamp", "material-tamper", "truncated"],
)
def test_tampered_snapshot_fails_closed(tmp_path, mutation) -> None:
    path = tmp_path / "proofs.sqlite3"
    SQLiteDerivProofStore(path).persist(_state())
    with sqlite3.connect(path) as connection:
        payload = connection.execute("SELECT payload FROM deriv_proof_state").fetchone()[0]
        data = json.loads(payload)
        if mutation == "malformed-json":
            changed = "{"
        elif mutation == "invalid-timestamp":
            data["entries"][0]["valid_from"] = "not-a-time"
            changed = json.dumps(data, sort_keys=True, separators=(",", ":"))
        elif mutation == "material-tamper":
            data["entries"][0]["candidate_material_hash"] = "sha256:" + "0" * 64
            changed = json.dumps(data, sort_keys=True, separators=(",", ":"))
        elif mutation == "truncated":
            changed = payload[:-10]
        else:
            changed = payload
        digest = "sha256:" + __import__("hashlib").sha256(changed.encode()).hexdigest()
        if mutation == "hash-mismatch":
            digest = "sha256:" + "0" * 64
        connection.execute("UPDATE deriv_proof_state SET payload=?, payload_hash=?", (changed, digest))
    with pytest.raises(DerivProofStoreError):
        SQLiteDerivProofStore(path).load()


@pytest.mark.parametrize("metadata", [None, "future", "malformed"])
def test_missing_unknown_or_malformed_schema_metadata_fails_closed(tmp_path, metadata) -> None:
    path = tmp_path / "proofs.sqlite3"
    SQLiteDerivProofStore(path)
    with sqlite3.connect(path) as connection:
        if metadata is None:
            connection.execute("DELETE FROM deriv_proof_store_metadata")
        elif metadata == "future":
            connection.execute("UPDATE deriv_proof_store_metadata SET schema_version=?", (DERIV_PROOF_STORE_SCHEMA_VERSION + 1,))
        else:
            connection.execute("UPDATE deriv_proof_store_metadata SET schema_version='bad'")
    with pytest.raises(DerivProofStoreError):
        SQLiteDerivProofStore(path)


def test_existing_empty_or_non_database_file_is_not_treated_as_new_store(tmp_path) -> None:
    for name, content in (("empty.sqlite3", b""), ("bad.sqlite3", b"not sqlite")):
        path = tmp_path / name
        path.write_bytes(content)
        with pytest.raises(DerivProofStoreError):
            SQLiteDerivProofStore(path)


def test_missing_required_snapshot_column_fails_closed(tmp_path) -> None:
    path = tmp_path / "missing-column.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE deriv_proof_store_metadata (singleton_id INTEGER PRIMARY KEY, schema_version INTEGER NOT NULL)"
        )
        connection.execute(
            "CREATE TABLE deriv_proof_state (singleton_id INTEGER PRIMARY KEY, schema_version INTEGER NOT NULL, payload TEXT NOT NULL)"
        )
        connection.execute("INSERT INTO deriv_proof_store_metadata VALUES (1, 1)")
        connection.execute("INSERT INTO deriv_proof_state VALUES (1, 1, '{}')")
    store = SQLiteDerivProofStore(path)
    with pytest.raises(DerivProofStoreError):
        store.load()


def test_transaction_failure_preserves_previous_complete_snapshot(tmp_path) -> None:
    path = tmp_path / "proofs.sqlite3"
    store = SQLiteDerivProofStore(path)
    original = _state()
    store.persist(original)
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TRIGGER reject_proof_update BEFORE UPDATE ON deriv_proof_state BEGIN SELECT RAISE(ABORT, 'injected failure'); END")
    expanded = DerivDurableProofState(original.registry, original.revocations + (
        DerivProofGovernanceRevocation(
            schema_version=1, revocation_id="offline:revocation:Z9",
            target_kind=DerivGovernanceRevocationTarget.CANDIDATE,
            target_id="unrelated-candidate", reason=DerivGovernanceRevocationReason.REVOKED,
            revoked_by="offline:reviewer", revoked_at=_ACTIVE_AT,
        ),
    ))
    with pytest.raises(sqlite3.IntegrityError, match="injected failure"):
        store.persist(expanded)
    assert SQLiteDerivProofStore(path).load() == original
