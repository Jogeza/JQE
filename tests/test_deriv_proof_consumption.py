"""Offline tests for revocation-aware Deriv proof consumption."""

from dataclasses import FrozenInstanceError, replace
import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest

from broker.deriv_contract_spec import (
    _AUTHORIZED_LOSS_MODEL_PROOFS,
    current_deriv_multiplier_specification,
    evaluate_deriv_quantity_capability,
)
from broker.deriv_proof_consumption import (
    DERIV_PROOF_CONSUMPTION_SCHEMA_VERSION,
    DerivProofConsumptionReason,
    DerivProofConsumptionRequest,
    DerivProofConsumptionState,
    validate_authoritative_proof_for_capability,
)
from broker.deriv_proof_registration import (
    DerivGovernanceRevocationReason,
    DerivGovernanceRevocationTarget,
)
from broker.deriv_proof_registry import DerivProofRegistryState
from risk.position_sizing import authorize_execution_quantity

_registration_spec = importlib.util.spec_from_file_location(
    "jqe_test_deriv_proof_registration",
    Path(__file__).with_name("test_deriv_proof_registration.py"),
)
assert _registration_spec is not None and _registration_spec.loader is not None
_registration_fixtures = importlib.util.module_from_spec(_registration_spec)
_registration_spec.loader.exec_module(_registration_fixtures)
_SCOPE_P1 = _registration_fixtures._SCOPE_P1
_admit = _registration_fixtures._admit
_revocation = _registration_fixtures._revocation


def _request(entry=None, **changes):
    entry = entry or _admit().registry.entries[0]
    values = {
        "schema_version": DERIV_PROOF_CONSUMPTION_SCHEMA_VERSION,
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
    }
    values.update(changes)
    return DerivProofConsumptionRequest(**values)


def test_empty_isolated_registry_has_no_available_proof() -> None:
    result = validate_authoritative_proof_for_capability(
        DerivProofRegistryState(), _request()
    )
    assert result.state is DerivProofConsumptionState.PROOF_UNAVAILABLE
    assert result.reason_codes == frozenset(
        {DerivProofConsumptionReason.NO_MATCHING_PROOF}
    )


def test_complete_isolated_chain_produces_exact_available_proof_only() -> None:
    admitted = _admit()
    before = admitted.registry
    result = validate_authoritative_proof_for_capability(before, _request(before.entries[0]))
    assert result.state is DerivProofConsumptionState.PROOF_AVAILABLE
    assert result.authoritative_loss_model_proof_available is True
    assert result.entry is before.entries[0]
    assert admitted.registry == before


def test_exact_applicability_does_not_widen_or_retarget() -> None:
    admitted = _admit()
    request = _request(
        admitted.registry.entries[0],
        applicability=replace(_SCOPE_P1, symbol="OFFLINE_TEST_SYMBOL_P2"),
    )
    result = validate_authoritative_proof_for_capability(admitted.registry, request)
    assert result.state is DerivProofConsumptionState.PROOF_UNAVAILABLE
    assert result.reason_codes == frozenset(
        {DerivProofConsumptionReason.APPLICABILITY_MISMATCH}
    )


@pytest.mark.parametrize(
    "target_kind,target_id,reason,expected",
    [
        (DerivGovernanceRevocationTarget.REGISTERED_PROOF, "offline:test-fixture:proof-R1", DerivGovernanceRevocationReason.REVOKED, DerivProofConsumptionReason.PROOF_REVOKED),
        (DerivGovernanceRevocationTarget.CANDIDATE, "offline:test-fixture:registration-candidate-C1", DerivGovernanceRevocationReason.REVOKED, DerivProofConsumptionReason.CANDIDATE_REVOKED),
        (DerivGovernanceRevocationTarget.INDEPENDENT_VERIFICATION, "offline:test-fixture:independent-verification-V1", DerivGovernanceRevocationReason.REVOKED, DerivProofConsumptionReason.VERIFICATION_REVOKED),
        (DerivGovernanceRevocationTarget.INDEPENDENT_VERIFICATION, "offline:test-fixture:independent-verification-V1", DerivGovernanceRevocationReason.SUPERSEDED, DerivProofConsumptionReason.VERIFICATION_SUPERSEDED),
    ],
)
def test_revocation_and_supersession_disable_consumption_without_erasing_history(
    target_kind, target_id, reason, expected
) -> None:
    admitted = _admit()
    record = _revocation(target_kind, target_id, reason)
    result = validate_authoritative_proof_for_capability(
        admitted.registry, _request(admitted.registry.entries[0]), (record,)
    )
    assert result.state is DerivProofConsumptionState.PROOF_REVOKED
    assert expected in result.reason_codes
    assert len(admitted.registry.entries) == 1


@pytest.mark.parametrize(
    "change,expected",
    [
        ({"candidate_material_hash": "sha256:" + "3" * 64}, DerivProofConsumptionReason.MATERIAL_HASH_MISMATCH),
        ({"candidate_id": "offline:test-fixture:changed-candidate"}, DerivProofConsumptionReason.LINEAGE_MISMATCH),
        ({"source_assessment_id": "offline:test-fixture:changed-assessment"}, DerivProofConsumptionReason.LINEAGE_MISMATCH),
        ({"review_decision_id": "offline:test-fixture:changed-review"}, DerivProofConsumptionReason.LINEAGE_MISMATCH),
        ({"artifact_ids": ("offline:test-fixture:changed-artifact",)}, DerivProofConsumptionReason.LINEAGE_MISMATCH),
        ({"artifact_content_hashes": ("sha256:" + "4" * 64,)}, DerivProofConsumptionReason.MATERIAL_HASH_MISMATCH),
        ({"claim_ids": ("offline:test-fixture:changed-claim",)}, DerivProofConsumptionReason.LINEAGE_MISMATCH),
        ({"loss_model_id": "offline:test-fixture:changed-model"}, DerivProofConsumptionReason.LINEAGE_MISMATCH),
        ({"evidence_source_id": "offline:test-fixture:changed-source"}, DerivProofConsumptionReason.LINEAGE_MISMATCH),
    ],
)
def test_changed_material_or_lineage_fails_closed(change, expected) -> None:
    admitted = _admit()
    result = validate_authoritative_proof_for_capability(
        admitted.registry, _request(admitted.registry.entries[0], **change)
    )
    assert result.state is DerivProofConsumptionState.PROOF_UNAVAILABLE
    assert expected in result.reason_codes


def test_multiple_exact_entries_are_a_registry_conflict_and_never_selected() -> None:
    first = _admit().registry.entries[0]
    second = replace(
        first,
        proof_id="offline:test-fixture:proof-R2",
        admission_id="offline:test-fixture:admission-M2",
        candidate_id="offline:test-fixture:candidate-C2",
    )
    registry = DerivProofRegistryState((first, second))
    result = validate_authoritative_proof_for_capability(registry, _request(first))
    assert result.state is DerivProofConsumptionState.PROOF_CONFLICT
    assert result.entry is None


def test_conflicting_revocations_fail_closed() -> None:
    admitted = _admit()
    first = _revocation(
        DerivGovernanceRevocationTarget.INDEPENDENT_VERIFICATION,
        admitted.registry.entries[0].verification_decision_id,
    )
    second = replace(
        first,
        revocation_id="offline:test-fixture:revocation-R2",
        reason=DerivGovernanceRevocationReason.SUPERSEDED,
        superseded_by_id="offline:test-fixture:replacement-V2",
    )
    result = validate_authoritative_proof_for_capability(
        admitted.registry, _request(admitted.registry.entries[0]), (first, second)
    )
    assert result.state is DerivProofConsumptionState.PROOF_CONFLICT
    assert result.reason_codes == frozenset(
        {DerivProofConsumptionReason.REVOCATION_CONFLICT}
    )


def test_malformed_caller_supplied_registry_fails_closed() -> None:
    malformed = object.__new__(DerivProofRegistryState)
    object.__setattr__(malformed, "entries", ("not-an-entry",))
    result = validate_authoritative_proof_for_capability(malformed, _request())
    assert result.state is DerivProofConsumptionState.PROOF_UNAVAILABLE
    assert result.reason_codes == frozenset(
        {DerivProofConsumptionReason.MALFORMED_REGISTRY_STATE}
    )


def test_consumption_is_deterministic_and_inputs_are_immutable() -> None:
    admitted = _admit()
    request = _request(admitted.registry.entries[0])
    first = validate_authoritative_proof_for_capability(admitted.registry, request)
    second = validate_authoritative_proof_for_capability(admitted.registry, request)
    assert first == second
    with pytest.raises(FrozenInstanceError):
        request.proof_id = "changed"
    with pytest.raises(FrozenInstanceError):
        admitted.registry.entries = ()


def test_available_proof_remains_separate_from_risk_and_quantity_authority() -> None:
    admitted = _admit()
    consumption = validate_authoritative_proof_for_capability(
        admitted.registry, _request(admitted.registry.entries[0])
    )
    capability = evaluate_deriv_quantity_capability(
        current_deriv_multiplier_specification(), consumption
    )
    sizing = authorize_execution_quantity(
        broker="deriv", balance=10_000, risk_percent=0.5, entry=100, stop_loss=92
    )
    assert capability.authoritative_loss_model_proof_available is True
    assert capability.stop_risk_authorizable is False
    assert sizing.quantity is None
    assert sizing.risk_verifiable is False


def test_production_registry_and_capability_remain_empty_and_fail_closed() -> None:
    capability = evaluate_deriv_quantity_capability(
        current_deriv_multiplier_specification()
    )
    sizing = authorize_execution_quantity(
        broker="deriv", balance=10_000, risk_percent=0.5, entry=100, stop_loss=92
    )
    assert len(_AUTHORIZED_LOSS_MODEL_PROOFS) == 0
    assert capability.proof_consumption_state is DerivProofConsumptionState.PROOF_UNAVAILABLE
    assert capability.authoritative_loss_model_proof_available is False
    assert capability.stop_risk_authorizable is False
    assert sizing.quantity is None


def test_consumption_module_is_structurally_isolated() -> None:
    source = Path("broker/deriv_proof_consumption.py").read_text(encoding="utf-8")
    forbidden = (
        "deriv_gateway",
        "submit_order",
        "OrderRequest",
        "ExecutionIntent",
        "ExecutionPolicy",
        "os.environ",
        "getenv(",
        "requests.",
        "websockets",
    )
    assert all(token not in source for token in forbidden)
    with patch("broker.deriv_gateway.DerivGateway") as gateway, patch(
        "broker.deriv_gateway.websockets.connect"
    ) as connect:
        admitted = _admit()
        validate_authoritative_proof_for_capability(
            admitted.registry, _request(admitted.registry.entries[0])
        )
    gateway.assert_not_called()
    connect.assert_not_called()
