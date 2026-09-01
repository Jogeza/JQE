"""Offline tests for proof-gated Deriv financial loss-model evaluation."""

from dataclasses import FrozenInstanceError, replace
from decimal import Decimal
import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest

from broker.deriv_contract_spec import (
    _AUTHORIZED_LOSS_MODEL_PROOFS,
    current_deriv_multiplier_specification,
    evaluate_deriv_quantity_capability,
)
from broker.deriv_loss_model import (
    DERIV_LOSS_EVALUATION_SCHEMA_VERSION,
    DerivFinancialInput,
    DerivLossEvaluationReason,
    DerivLossEvaluationRequest,
    DerivLossEvaluationState,
    evaluate_authoritative_deriv_loss_model,
)
from broker.deriv_proof_consumption import (
    DERIV_PROOF_CONSUMPTION_SCHEMA_VERSION,
    DerivProofConsumptionReason,
    DerivProofConsumptionRequest,
    DerivProofConsumptionResult,
    DerivProofConsumptionState,
    validate_authoritative_proof_for_capability,
)
from broker.deriv_proof_registration import (
    DerivGovernanceRevocationTarget,
)
from broker.deriv_proof_registry import DerivProofRegistryState
from risk.position_sizing import authorize_execution_quantity


_registration_spec = importlib.util.spec_from_file_location(
    "jqe_loss_test_registration_fixtures",
    Path(__file__).with_name("test_deriv_proof_registration.py"),
)
assert _registration_spec is not None and _registration_spec.loader is not None
_registration_fixtures = importlib.util.module_from_spec(_registration_spec)
_registration_spec.loader.exec_module(_registration_fixtures)
_admit = _registration_fixtures._admit
_revocation = _registration_fixtures._revocation


def _proof_request(entry):
    return DerivProofConsumptionRequest(
        schema_version=DERIV_PROOF_CONSUMPTION_SCHEMA_VERSION,
        proof_id=entry.proof_id,
        admission_id=entry.admission_id,
        candidate_id=entry.candidate_id,
        candidate_material_hash=entry.candidate_material_hash,
        verification_decision_id=entry.verification_decision_id,
        source_assessment_id=entry.source_assessment_id,
        review_decision_id=entry.review_decision_id,
        artifact_ids=entry.artifact_ids,
        artifact_content_hashes=entry.artifact_content_hashes,
        claim_ids=entry.claim_ids,
        applicability=entry.applicability,
        loss_model_id=entry.loss_model_id,
        loss_model_version=entry.loss_model_version,
        evidence_source_id=entry.evidence_source_id,
    )


def _evaluation_bundle(*, registry=None, revocations=(), **changes):
    admitted = _admit()
    registry = admitted.registry if registry is None else registry
    entry = admitted.registry.entries[0]
    proof_request = _proof_request(entry)
    proof_result = validate_authoritative_proof_for_capability(
        registry, proof_request, revocations
    )
    values = {
        "schema_version": DERIV_LOSS_EVALUATION_SCHEMA_VERSION,
        "registry": registry,
        "proof_request": proof_request,
        "proof_result": proof_result,
        "revocations": revocations,
        "applicability": entry.applicability,
        "loss_model_id": entry.loss_model_id,
        "loss_model_version": entry.loss_model_version,
        "candidate_material_hash": entry.candidate_material_hash,
        "evidence_source_id": entry.evidence_source_id,
        "financial_inputs": (
            DerivFinancialInput(
                semantic_id="offline:test-fixture:proposed-input",
                unit_id="offline:test-fixture:explicit-unit",
                value=Decimal("1"),
            ),
        ),
    }
    values.update(changes)
    return DerivLossEvaluationRequest(**values), admitted.registry


def test_complete_authoritative_chain_stops_at_unsupported_model() -> None:
    request, registry_before = _evaluation_bundle()
    result = evaluate_authoritative_deriv_loss_model(request)
    assert result.state is DerivLossEvaluationState.LOSS_MODEL_UNSUPPORTED
    assert result.reason_codes == frozenset(
        {DerivLossEvaluationReason.MODEL_UNSUPPORTED}
    )
    assert result.monetary_loss is None
    assert result.monetary_unit_id is None
    assert request.registry == registry_before


def test_empty_registry_cannot_reach_model_evaluation() -> None:
    request, _ = _evaluation_bundle(registry=DerivProofRegistryState())
    result = evaluate_authoritative_deriv_loss_model(request)
    assert result.state is DerivLossEvaluationState.PROOF_UNAVAILABLE
    assert result.reason_codes == frozenset(
        {DerivLossEvaluationReason.PROOF_UNAVAILABLE}
    )


def test_revoked_proof_cannot_reach_model_evaluation() -> None:
    admitted = _admit()
    revocation = _revocation(
        DerivGovernanceRevocationTarget.REGISTERED_PROOF,
        admitted.registry.entries[0].proof_id,
    )
    request, _ = _evaluation_bundle(
        registry=admitted.registry, revocations=(revocation,)
    )
    result = evaluate_authoritative_deriv_loss_model(request)
    assert result.state is DerivLossEvaluationState.PROOF_UNAVAILABLE


def test_forged_available_result_is_not_a_bearer_token() -> None:
    request, _ = _evaluation_bundle()
    assert request.proof_result.entry is not None
    unrelated = replace(
        request.proof_result.entry,
        proof_id="offline:test-fixture:forged-proof",
        admission_id="offline:test-fixture:forged-admission",
        candidate_id="offline:test-fixture:forged-candidate",
    )
    forged = DerivProofConsumptionResult(
        DerivProofConsumptionState.PROOF_AVAILABLE,
        frozenset({DerivProofConsumptionReason.EXACT_ACTIVE_PROOF}),
        unrelated,
    )
    result = evaluate_authoritative_deriv_loss_model(
        replace(request, proof_result=forged)
    )
    assert result.state is DerivLossEvaluationState.LOSS_CONFLICT
    assert result.reason_codes == frozenset(
        {DerivLossEvaluationReason.PROOF_LINEAGE_INVALID}
    )
    assert result.monetary_loss is None


@pytest.mark.parametrize(
    "applicability_change",
    [
        {"contract_family": "OFFLINE_OTHER_CONTRACT"},
        {"symbol": "OFFLINE_OTHER_SYMBOL"},
        {"quantity_basis": "offline-other-quantity"},
        {"stop_loss_semantic_id": "offline:test-fixture:other-stop"},
        {"multiplier_semantics_id": "offline:test-fixture:other-multiplier"},
        {"symbol_capability_scope": "offline:test-fixture:other-scope"},
        {"account_currency": "OFFLINE_CURRENCY"},
        {"environment": "offline-environment"},
    ],
)
def test_every_applicability_dimension_requires_exact_match(
    applicability_change,
) -> None:
    request, _ = _evaluation_bundle()
    changed_scope = replace(request.applicability, **applicability_change)
    result = evaluate_authoritative_deriv_loss_model(
        replace(request, applicability=changed_scope)
    )
    assert result.state is DerivLossEvaluationState.LOSS_CONFLICT
    assert DerivLossEvaluationReason.APPLICABILITY_MISMATCH in result.reason_codes


@pytest.mark.parametrize(
    "change,expected",
    [
        ({"loss_model_id": "offline:test-fixture:model-M2"}, DerivLossEvaluationReason.LOSS_MODEL_ID_MISMATCH),
        ({"loss_model_version": 2}, DerivLossEvaluationReason.LOSS_MODEL_VERSION_MISMATCH),
        ({"candidate_material_hash": "sha256:" + "9" * 64}, DerivLossEvaluationReason.MATERIAL_HASH_MISMATCH),
        ({"evidence_source_id": "offline:test-fixture:source-S2"}, DerivLossEvaluationReason.EVIDENCE_SOURCE_MISMATCH),
    ],
)
def test_model_and_source_identity_must_match_exactly(change, expected) -> None:
    request, _ = _evaluation_bundle()
    result = evaluate_authoritative_deriv_loss_model(replace(request, **change))
    assert result.state is DerivLossEvaluationState.LOSS_CONFLICT
    assert expected in result.reason_codes


def test_missing_financial_inputs_is_controlled_and_fail_closed() -> None:
    request, _ = _evaluation_bundle(financial_inputs=())
    result = evaluate_authoritative_deriv_loss_model(request)
    assert result.state is DerivLossEvaluationState.LOSS_INPUT_INVALID
    assert result.reason_codes == frozenset(
        {DerivLossEvaluationReason.INPUT_MISSING}
    )


@pytest.mark.parametrize(
    "value",
    [Decimal("0"), Decimal("-1"), Decimal("NaN"), Decimal("Infinity")],
)
def test_invalid_numeric_domains_are_rejected(value) -> None:
    request, _ = _evaluation_bundle(
        financial_inputs=(
            DerivFinancialInput("offline:test:input", "offline:test:unit", value),
        )
    )
    result = evaluate_authoritative_deriv_loss_model(request)
    assert result.state is DerivLossEvaluationState.LOSS_INPUT_INVALID
    assert result.reason_codes == frozenset(
        {DerivLossEvaluationReason.NUMERIC_DOMAIN_INVALID}
    )


@pytest.mark.parametrize("value", [Decimal("1E-1000"), Decimal("1E+1000")])
def test_finite_decimal_boundaries_remain_deterministically_unsupported(value) -> None:
    request, _ = _evaluation_bundle(
        financial_inputs=(
            DerivFinancialInput("offline:test:input", "offline:test:unit", value),
        )
    )
    first = evaluate_authoritative_deriv_loss_model(request)
    second = evaluate_authoritative_deriv_loss_model(request)
    assert first == second
    assert first.state is DerivLossEvaluationState.LOSS_MODEL_UNSUPPORTED


@pytest.mark.parametrize("value", [1.0, 1, "1", None])
def test_financial_inputs_reject_ambiguous_non_decimal_values(value) -> None:
    with pytest.raises(ValueError, match="Decimal"):
        DerivFinancialInput("offline:test:input", "offline:test:unit", value)


def test_request_models_are_strict_and_immutable() -> None:
    request, _ = _evaluation_bundle()
    with pytest.raises(FrozenInstanceError):
        request.loss_model_id = "changed"
    with pytest.raises(ValueError, match="schema"):
        replace(request, schema_version=2)
    with pytest.raises(ValueError, match="unique"):
        item = request.financial_inputs[0]
        replace(request, financial_inputs=(item, item))
    with pytest.raises(ValueError, match="SHA-256"):
        replace(request, candidate_material_hash="sha256:bad")


def test_loss_boundary_grants_no_risk_quantity_or_execution_authority() -> None:
    request, _ = _evaluation_bundle()
    loss_result = evaluate_authoritative_deriv_loss_model(request)
    capability = evaluate_deriv_quantity_capability(
        current_deriv_multiplier_specification(),
        request.proof_result,
        loss_result,
    )
    sizing = authorize_execution_quantity(
        broker="deriv", balance=10_000, risk_percent=0.5, entry=100, stop_loss=92
    )
    assert capability.authoritative_loss_model_proof_available is True
    assert capability.authoritative_loss_model_evaluated is False
    assert capability.stop_risk_authorizable is False
    assert sizing.quantity is None
    assert sizing.risk_verifiable is False


def test_production_loss_evaluation_remains_unavailable() -> None:
    request, _ = _evaluation_bundle(registry=DerivProofRegistryState())
    loss_result = evaluate_authoritative_deriv_loss_model(request)
    capability = evaluate_deriv_quantity_capability(
        current_deriv_multiplier_specification(), loss_evaluation=loss_result
    )
    assert len(_AUTHORIZED_LOSS_MODEL_PROOFS) == 0
    assert loss_result.state is DerivLossEvaluationState.PROOF_UNAVAILABLE
    assert capability.authoritative_loss_model_proof_available is False
    assert capability.authoritative_loss_model_evaluated is False
    assert capability.stop_risk_authorizable is False


def test_loss_evaluation_module_is_structurally_isolated() -> None:
    source = Path("broker/deriv_loss_model.py").read_text(encoding="utf-8")
    forbidden = (
        "deriv_gateway",
        "submit_order",
        "OrderRequest",
        "ExecutionIntent",
        "ExecutionPolicy",
        "position_sizing",
        "authorize_execution_quantity",
        "os.environ",
        "getenv(",
        "requests.",
        "websockets",
    )
    assert all(token not in source for token in forbidden)
    with patch("broker.deriv_gateway.DerivGateway") as gateway, patch(
        "broker.deriv_gateway.websockets.connect"
    ) as connect:
        request, registry_before = _evaluation_bundle()
        evaluate_authoritative_deriv_loss_model(request)
        assert request.registry == registry_before
    gateway.assert_not_called()
    connect.assert_not_called()
