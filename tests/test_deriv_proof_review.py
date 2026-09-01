"""Offline tests for non-authoritative Deriv proof-review assessments."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime, timezone
from unittest.mock import patch

import pytest

from broker.deriv_contract_spec import (
    current_deriv_multiplier_specification,
    evaluate_deriv_quantity_capability,
)
from broker.deriv_evidence import (
    DerivEvidenceApplicability,
    DerivEvidenceArtifact,
    DerivEvidenceClaim,
    DerivEvidenceClaimType,
    DerivEvidenceRegistry,
    DerivEvidenceReviewState,
)
from broker.deriv_evidence_review import (
    DerivEvidenceDecisionState,
    DerivEvidenceReviewDecision,
    DerivEvidenceReviewReason,
)
from broker.deriv_proof_review import (
    DERIV_PROOF_REVIEW_SCHEMA_VERSION,
    DerivProofReviewAssessment,
    DerivProofReviewReason,
    DerivProofReviewState,
    validate_deriv_proof_review_assessment,
)
from risk.position_sizing import authorize_execution_quantity


_ARTIFACT_ID = "offline:test-fixture:proof-review-artifact"
_CLAIM_ID = "offline:test-fixture:proof-review-claim"
_DECISION_ID = "offline:test-fixture:evidence-review-decision"
_HASH = "sha256:" + "a" * 64
_SCOPE = DerivEvidenceApplicability(
    broker="deriv", contract_family="OFFLINE_TEST_FIXTURE",
    symbol="OFFLINE_TEST_SYMBOL", quantity_basis="offline-test-basis",
    stop_loss_semantic_id="offline:test-fixture:stop",
    multiplier_semantics_id="offline:test-fixture:multiplier",
    symbol_capability_scope="offline:test-fixture:symbol-scope",
)


def _artifact(*, content_hash=_HASH, claim_state=DerivEvidenceReviewState.REVIEWED):
    claim = DerivEvidenceClaim(
        claim_id=_CLAIM_ID, artifact_id=_ARTIFACT_ID,
        claim_type=DerivEvidenceClaimType.QUANTITY_BASIS_SEMANTICS,
        subject="offline fixture subject", value="offline fixture value",
        applicability=_SCOPE, review_state=claim_state,
    )
    return DerivEvidenceArtifact(
        schema_version=1, artifact_id=_ARTIFACT_ID,
        source_identifier="offline:test-fixture:source",
        source_title="Synthetic Offline Proof Review Fixture",
        source_publisher="JQE tests", source_version="fixture-v1",
        recorded_date=date(2026, 9, 1), content_hash=content_hash,
        claims=(claim,), review_state=DerivEvidenceReviewState.REVIEWED,
    )


def _decision(state=DerivEvidenceDecisionState.APPROVED_FOR_PROOF_REVIEW):
    if state is DerivEvidenceDecisionState.APPROVED_FOR_PROOF_REVIEW:
        reasons = frozenset({DerivEvidenceReviewReason.EVIDENCE_SET_COMPLETE})
        claim_state = DerivEvidenceReviewState.REVIEWED
    elif state is DerivEvidenceDecisionState.REJECTED:
        reasons = frozenset({DerivEvidenceReviewReason.CLAIM_REJECTED})
        claim_state = DerivEvidenceReviewState.REJECTED
    else:
        reasons = frozenset({DerivEvidenceReviewReason.CLAIM_UNREVIEWED})
        claim_state = DerivEvidenceReviewState.UNREVIEWED
    decision = DerivEvidenceReviewDecision(
        schema_version=1, decision_id=_DECISION_ID,
        artifact_ids=(_ARTIFACT_ID,), artifact_content_hashes=(_HASH,),
        claim_ids=(_CLAIM_ID,), state=state, reason_codes=reasons,
        reviewer_id="offline:evidence-reviewer",
        reviewed_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        applicability=_SCOPE, rationale="Synthetic offline fixture",
    )
    return decision, _artifact(claim_state=claim_state)


def _assessment(state, reasons, **changes):
    values = {
        "schema_version": DERIV_PROOF_REVIEW_SCHEMA_VERSION,
        "assessment_id": "offline:test-fixture:proof-review-assessment",
        "review_decision_id": _DECISION_ID,
        "artifact_ids": (_ARTIFACT_ID,),
        "artifact_content_hashes": (_HASH,),
        "claim_ids": (_CLAIM_ID,),
        "state": state,
        "reason_codes": frozenset(reasons),
        "reviewer_id": "offline:proof-reviewer",
        "reviewed_at": datetime(2026, 9, 1, tzinfo=timezone.utc),
        "applicability": _SCOPE,
        "rationale": "Synthetic offline proof-review fixture",
    }
    values.update(changes)
    return DerivProofReviewAssessment(**values)


def _validate(assessment, decision=None, artifact=None):
    if decision is None:
        decision, default_artifact = _decision()
        artifact = artifact or default_artifact
    registry = DerivEvidenceRegistry().register(artifact or _artifact())
    return validate_deriv_proof_review_assessment(assessment, decision, registry)


def test_valid_ready_assessment_from_valid_advisory_approval() -> None:
    assessment = _assessment(
        DerivProofReviewState.READY_FOR_AUTHORITATIVE_PROOF_REVIEW,
        {DerivProofReviewReason.REVIEW_PACKAGE_CONSISTENT},
    )
    assert _validate(assessment).valid is True


def test_valid_insufficient_assessment() -> None:
    decision, artifact = _decision(DerivEvidenceDecisionState.INSUFFICIENT)
    assessment = _assessment(
        DerivProofReviewState.INSUFFICIENT,
        {DerivProofReviewReason.REVIEW_DECISION_NOT_APPROVED,
         DerivProofReviewReason.REVIEW_SCOPE_INCOMPLETE},
    )
    assert _validate(assessment, decision, artifact).valid is True


def test_valid_rejected_assessment() -> None:
    decision, artifact = _decision(DerivEvidenceDecisionState.REJECTED)
    assessment = _assessment(
        DerivProofReviewState.REJECTED,
        {DerivProofReviewReason.REVIEW_DECISION_NOT_APPROVED,
         DerivProofReviewReason.REVIEW_PACKAGE_CONFLICTING},
    )
    assert _validate(assessment, decision, artifact).valid is True


@pytest.mark.parametrize(
    "decision_state",
    [DerivEvidenceDecisionState.INSUFFICIENT, DerivEvidenceDecisionState.REJECTED],
)
def test_nonapproved_review_decision_prevents_ready(decision_state) -> None:
    decision, artifact = _decision(decision_state)
    assessment = _assessment(
        DerivProofReviewState.READY_FOR_AUTHORITATIVE_PROOF_REVIEW,
        {DerivProofReviewReason.REVIEW_PACKAGE_CONSISTENT},
    )
    result = _validate(assessment, decision, artifact)
    assert result.valid is False
    assert DerivProofReviewReason.REVIEW_DECISION_NOT_APPROVED in result.observed_reasons


def test_stale_review_decision_prevents_ready() -> None:
    decision, _ = _decision()
    assessment = _assessment(
        DerivProofReviewState.READY_FOR_AUTHORITATIVE_PROOF_REVIEW,
        {DerivProofReviewReason.REVIEW_PACKAGE_CONSISTENT},
    )
    result = _validate(
        assessment, decision, _artifact(content_hash="sha256:" + "b" * 64)
    )
    assert result.valid is False
    assert DerivProofReviewReason.REVIEW_DECISION_STALE in result.observed_reasons


def test_evidence_hash_change_invalidates_assessment_chain() -> None:
    assessment = _assessment(
        DerivProofReviewState.READY_FOR_AUTHORITATIVE_PROOF_REVIEW,
        {DerivProofReviewReason.REVIEW_PACKAGE_CONSISTENT},
    )
    decision, artifact = _decision()
    assert _validate(assessment, decision, artifact).valid is True
    replacement = _artifact(content_hash="sha256:" + "c" * 64)
    assert _validate(assessment, decision, replacement).valid is False


def test_applicability_mismatch_prevents_ready() -> None:
    assessment = _assessment(
        DerivProofReviewState.READY_FOR_AUTHORITATIVE_PROOF_REVIEW,
        {DerivProofReviewReason.REVIEW_PACKAGE_CONSISTENT},
        applicability=replace(_SCOPE, quantity_basis="other-offline-test-basis"),
    )
    result = _validate(assessment)
    assert result.valid is False
    assert DerivProofReviewReason.APPLICABILITY_MISMATCH in result.observed_reasons


def test_claim_set_mismatch_prevents_ready() -> None:
    assessment = _assessment(
        DerivProofReviewState.READY_FOR_AUTHORITATIVE_PROOF_REVIEW,
        {DerivProofReviewReason.REVIEW_PACKAGE_CONSISTENT},
        claim_ids=("offline:test-fixture:other-claim",),
    )
    result = _validate(assessment)
    assert result.valid is False
    assert DerivProofReviewReason.CLAIM_SET_MISMATCH in result.observed_reasons


@pytest.mark.parametrize("schema", [True, False, 1.0, "1", None])
def test_schema_version_is_strict(schema) -> None:
    with pytest.raises(ValueError, match="strict integer"):
        _assessment(
            DerivProofReviewState.INSUFFICIENT,
            {DerivProofReviewReason.REVIEW_SCOPE_INCOMPLETE},
            schema_version=schema,
        )


def test_future_schema_is_rejected() -> None:
    with pytest.raises(ValueError, match="unsupported"):
        _assessment(
            DerivProofReviewState.INSUFFICIENT,
            {DerivProofReviewReason.REVIEW_SCOPE_INCOMPLETE}, schema_version=2,
        )


@pytest.mark.parametrize("field,value", [("assessment_id", ""), ("assessment_id", None), ("reviewer_id", "   "), ("reviewer_id", 123)])
def test_malformed_assessment_and_reviewer_ids_are_rejected(field, value) -> None:
    with pytest.raises(ValueError, match="nonblank string"):
        _assessment(
            DerivProofReviewState.INSUFFICIENT,
            {DerivProofReviewReason.REVIEW_SCOPE_INCOMPLETE}, **{field: value},
        )


@pytest.mark.parametrize("reviewed_at", [datetime(2026, 9, 1), "2026-09-01", None])
def test_review_timestamp_must_be_timezone_aware(reviewed_at) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        _assessment(
            DerivProofReviewState.INSUFFICIENT,
            {DerivProofReviewReason.REVIEW_SCOPE_INCOMPLETE},
            reviewed_at=reviewed_at,
        )


@pytest.mark.parametrize("content_hash", [None, "sha256:abc", "sha1:" + "a" * 40, "sha256:" + "A" * 64])
def test_malformed_hash_is_rejected(content_hash) -> None:
    with pytest.raises(ValueError, match="sha256"):
        _assessment(
            DerivProofReviewState.INSUFFICIENT,
            {DerivProofReviewReason.REVIEW_SCOPE_INCOMPLETE},
            artifact_content_hashes=(content_hash,),
        )


def test_duplicate_artifact_ids_are_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate artifact IDs"):
        _assessment(
            DerivProofReviewState.INSUFFICIENT,
            {DerivProofReviewReason.REVIEW_SCOPE_INCOMPLETE},
            artifact_ids=(_ARTIFACT_ID, _ARTIFACT_ID),
            artifact_content_hashes=(_HASH, _HASH),
        )


def test_duplicate_claim_ids_are_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate claim IDs"):
        _assessment(
            DerivProofReviewState.INSUFFICIENT,
            {DerivProofReviewReason.REVIEW_SCOPE_INCOMPLETE},
            claim_ids=(_CLAIM_ID, _CLAIM_ID),
        )


def test_unknown_reason_code_is_rejected() -> None:
    with pytest.raises(ValueError, match="recognized reasons"):
        _assessment(
            DerivProofReviewState.INSUFFICIENT, {"UNKNOWN_REASON"},
        )


def test_ready_requires_nonempty_evidence_package() -> None:
    with pytest.raises(ValueError, match="nonempty evidence"):
        _assessment(
            DerivProofReviewState.READY_FOR_AUTHORITATIVE_PROOF_REVIEW,
            {DerivProofReviewReason.REVIEW_PACKAGE_CONSISTENT},
            artifact_ids=(), artifact_content_hashes=(), claim_ids=(),
        )


def test_missing_review_decision_is_rejected() -> None:
    assessment = _assessment(
        DerivProofReviewState.READY_FOR_AUTHORITATIVE_PROOF_REVIEW,
        {DerivProofReviewReason.REVIEW_PACKAGE_CONSISTENT},
    )
    with pytest.raises(ValueError, match="review_decision"):
        validate_deriv_proof_review_assessment(
            assessment, None, DerivEvidenceRegistry()
        )


def test_assessment_is_immutable() -> None:
    assessment = _assessment(
        DerivProofReviewState.READY_FOR_AUTHORITATIVE_PROOF_REVIEW,
        {DerivProofReviewReason.REVIEW_PACKAGE_CONSISTENT},
    )
    with pytest.raises(FrozenInstanceError):
        assessment.reviewer_id = "changed"


def test_ready_assessment_remains_non_authoritative() -> None:
    assessment = _assessment(
        DerivProofReviewState.READY_FOR_AUTHORITATIVE_PROOF_REVIEW,
        {DerivProofReviewReason.REVIEW_PACKAGE_CONSISTENT},
    )
    assert _validate(assessment).valid is True
    for name in ("to_proof", "make_proof", "register_proof", "authorize"):
        assert not hasattr(assessment, name)
    capability = evaluate_deriv_quantity_capability(
        current_deriv_multiplier_specification()
    )
    sizing = authorize_execution_quantity(
        broker="deriv", balance=10_000, risk_percent=0.5,
        entry=100, stop_loss=92,
    )
    assert capability.stop_risk_authorizable is False
    assert sizing.quantity is None
    assert sizing.risk_verifiable is False


def test_assessment_constructs_no_gateway_or_network_connection() -> None:
    assessment = _assessment(
        DerivProofReviewState.READY_FOR_AUTHORITATIVE_PROOF_REVIEW,
        {DerivProofReviewReason.REVIEW_PACKAGE_CONSISTENT},
    )
    with patch("broker.deriv_gateway.DerivGateway") as gateway, patch(
        "broker.deriv_gateway.websockets.connect"
    ) as connect:
        assert _validate(assessment).valid is True
    gateway.assert_not_called()
    connect.assert_not_called()


def test_assessment_validation_is_deterministic() -> None:
    assessment = _assessment(
        DerivProofReviewState.READY_FOR_AUTHORITATIVE_PROOF_REVIEW,
        {DerivProofReviewReason.REVIEW_PACKAGE_CONSISTENT},
    )
    decision, artifact = _decision()
    registry = DerivEvidenceRegistry().register(artifact)
    first = validate_deriv_proof_review_assessment(assessment, decision, registry)
    second = validate_deriv_proof_review_assessment(assessment, decision, registry)
    assert first == second
