"""Offline tests for advisory, non-authoritative evidence review decisions."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
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
    DERIV_EVIDENCE_REVIEW_SCHEMA_VERSION,
    DerivEvidenceDecisionState,
    DerivEvidenceReviewDecision,
    DerivEvidenceReviewReason,
    validate_deriv_evidence_review,
)
from risk.position_sizing import authorize_execution_quantity


_ARTIFACT_ID = "offline:test-fixture:review-artifact"
_CLAIM_ID = "offline:test-fixture:review-claim"
_HASH = "sha256:" + "a" * 64
_SCOPE = DerivEvidenceApplicability(
    broker="deriv",
    contract_family="OFFLINE_TEST_FIXTURE",
    symbol="OFFLINE_TEST_SYMBOL",
    quantity_basis="offline-test-basis",
    stop_loss_semantic_id="offline:test-fixture:stop",
    multiplier_semantics_id="offline:test-fixture:multiplier",
    symbol_capability_scope="offline:test-fixture:symbol-scope",
)


def _artifact(
    *,
    artifact_state=DerivEvidenceReviewState.REVIEWED,
    claim_state=DerivEvidenceReviewState.REVIEWED,
    content_hash=_HASH,
    applicability=_SCOPE,
    claim_value="offline fixture value",
) -> DerivEvidenceArtifact:
    claim = DerivEvidenceClaim(
        claim_id=_CLAIM_ID,
        artifact_id=_ARTIFACT_ID,
        claim_type=DerivEvidenceClaimType.QUANTITY_BASIS_SEMANTICS,
        subject="offline fixture subject",
        value=claim_value,
        applicability=applicability,
        review_state=claim_state,
    )
    return DerivEvidenceArtifact(
        schema_version=1,
        artifact_id=_ARTIFACT_ID,
        source_identifier="offline:test-fixture:source",
        source_title="Synthetic Offline Review Fixture",
        source_publisher="JQE tests",
        source_version="fixture-v1",
        recorded_date=datetime(2026, 9, 1, tzinfo=timezone.utc).date(),
        content_hash=content_hash,
        claims=(claim,),
        review_state=artifact_state,
    )


def _decision(state, reasons, **changes) -> DerivEvidenceReviewDecision:
    values = {
        "schema_version": DERIV_EVIDENCE_REVIEW_SCHEMA_VERSION,
        "decision_id": "offline:test-fixture:decision",
        "artifact_ids": (_ARTIFACT_ID,),
        "artifact_content_hashes": (_HASH,),
        "claim_ids": (_CLAIM_ID,),
        "state": state,
        "reason_codes": frozenset(reasons),
        "reviewer_id": "offline:test-reviewer",
        "reviewed_at": datetime(2026, 9, 1, tzinfo=timezone.utc),
        "applicability": _SCOPE,
        "rationale": "Synthetic offline review fixture",
    }
    values.update(changes)
    return DerivEvidenceReviewDecision(**values)


def _validate(decision, artifact=None):
    registry = DerivEvidenceRegistry().register(artifact or _artifact())
    return validate_deriv_evidence_review(decision, registry)


def test_valid_approved_for_proof_review_decision() -> None:
    decision = _decision(
        DerivEvidenceDecisionState.APPROVED_FOR_PROOF_REVIEW,
        {DerivEvidenceReviewReason.EVIDENCE_SET_COMPLETE},
    )
    assert _validate(decision).valid is True


def test_valid_rejected_decision() -> None:
    decision = _decision(
        DerivEvidenceDecisionState.REJECTED,
        {DerivEvidenceReviewReason.CLAIM_REJECTED},
    )
    artifact = _artifact(claim_state=DerivEvidenceReviewState.REJECTED)
    assert _validate(decision, artifact).valid is True


def test_valid_insufficient_decision() -> None:
    decision = _decision(
        DerivEvidenceDecisionState.INSUFFICIENT,
        {DerivEvidenceReviewReason.CLAIM_UNREVIEWED},
    )
    artifact = _artifact(claim_state=DerivEvidenceReviewState.UNREVIEWED)
    assert _validate(decision, artifact).valid is True


def test_empty_evidence_set_is_valid_only_as_insufficient() -> None:
    decision = _decision(
        DerivEvidenceDecisionState.INSUFFICIENT,
        {DerivEvidenceReviewReason.MISSING_REQUIRED_CLAIM},
        artifact_ids=(), artifact_content_hashes=(), claim_ids=(),
    )
    assert validate_deriv_evidence_review(
        decision, DerivEvidenceRegistry()
    ).valid is True


@pytest.mark.parametrize("schema", [True, False, 1.0, "1", None])
def test_schema_version_is_a_strict_integer(schema) -> None:
    with pytest.raises(ValueError, match="strict integer"):
        _decision(
            DerivEvidenceDecisionState.INSUFFICIENT,
            {DerivEvidenceReviewReason.CLAIM_UNREVIEWED},
            schema_version=schema,
        )


def test_future_schema_is_rejected() -> None:
    with pytest.raises(ValueError, match="unsupported"):
        _decision(
            DerivEvidenceDecisionState.INSUFFICIENT,
            {DerivEvidenceReviewReason.CLAIM_UNREVIEWED},
            schema_version=2,
        )


@pytest.mark.parametrize("decision_id", ["", "   ", None, 123])
def test_empty_and_malformed_decision_ids_are_rejected(decision_id) -> None:
    with pytest.raises(ValueError, match="nonblank string"):
        _decision(
            DerivEvidenceDecisionState.INSUFFICIENT,
            {DerivEvidenceReviewReason.CLAIM_UNREVIEWED},
            decision_id=decision_id,
        )


@pytest.mark.parametrize("reviewer_id", ["", "   ", None, 123])
def test_empty_and_malformed_reviewer_ids_are_rejected(reviewer_id) -> None:
    with pytest.raises(ValueError, match="nonblank string"):
        _decision(
            DerivEvidenceDecisionState.INSUFFICIENT,
            {DerivEvidenceReviewReason.CLAIM_UNREVIEWED},
            reviewer_id=reviewer_id,
        )


@pytest.mark.parametrize(
    "reviewed_at",
    ["2026-09-01", datetime(2026, 9, 1), None, 123],
)
def test_review_timestamp_must_be_timezone_aware(reviewed_at) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        _decision(
            DerivEvidenceDecisionState.INSUFFICIENT,
            {DerivEvidenceReviewReason.CLAIM_UNREVIEWED},
            reviewed_at=reviewed_at,
        )


def test_duplicate_artifact_ids_are_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate artifact IDs"):
        _decision(
            DerivEvidenceDecisionState.INSUFFICIENT,
            {DerivEvidenceReviewReason.CLAIM_UNREVIEWED},
            artifact_ids=(_ARTIFACT_ID, _ARTIFACT_ID),
            artifact_content_hashes=(_HASH, _HASH),
        )


def test_duplicate_claim_ids_are_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate claim IDs"):
        _decision(
            DerivEvidenceDecisionState.INSUFFICIENT,
            {DerivEvidenceReviewReason.CLAIM_UNREVIEWED},
            claim_ids=(_CLAIM_ID, _CLAIM_ID),
        )


@pytest.mark.parametrize(
    "content_hash", [None, "sha256:abc", "sha1:" + "a" * 40, "sha256:" + "A" * 64]
)
def test_malformed_content_hash_is_rejected(content_hash) -> None:
    with pytest.raises(ValueError, match="sha256"):
        _decision(
            DerivEvidenceDecisionState.INSUFFICIENT,
            {DerivEvidenceReviewReason.CLAIM_UNREVIEWED},
            artifact_content_hashes=(content_hash,),
        )


def test_approved_decision_requires_nonempty_evidence() -> None:
    with pytest.raises(ValueError, match="nonempty evidence"):
        _decision(
            DerivEvidenceDecisionState.APPROVED_FOR_PROOF_REVIEW,
            {DerivEvidenceReviewReason.EVIDENCE_SET_COMPLETE},
            artifact_ids=(), artifact_content_hashes=(), claim_ids=(),
        )


@pytest.mark.parametrize(
    "artifact_state,claim_state,reason",
    [
        (DerivEvidenceReviewState.UNREVIEWED, DerivEvidenceReviewState.REVIEWED,
         DerivEvidenceReviewReason.ARTIFACT_UNREVIEWED),
        (DerivEvidenceReviewState.REVIEWED, DerivEvidenceReviewState.UNREVIEWED,
         DerivEvidenceReviewReason.CLAIM_UNREVIEWED),
        (DerivEvidenceReviewState.REVIEWED, DerivEvidenceReviewState.REJECTED,
         DerivEvidenceReviewReason.CLAIM_REJECTED),
    ],
)
def test_nonreviewed_or_rejected_evidence_prevents_approval(
    artifact_state, claim_state, reason
) -> None:
    decision = _decision(
        DerivEvidenceDecisionState.APPROVED_FOR_PROOF_REVIEW,
        {DerivEvidenceReviewReason.EVIDENCE_SET_COMPLETE},
    )
    result = _validate(
        decision, _artifact(artifact_state=artifact_state, claim_state=claim_state)
    )
    assert result.valid is False
    assert reason in result.observed_reasons


def test_applicability_mismatch_prevents_approval() -> None:
    other_scope = replace(_SCOPE, quantity_basis="other-offline-test-basis")
    decision = _decision(
        DerivEvidenceDecisionState.APPROVED_FOR_PROOF_REVIEW,
        {DerivEvidenceReviewReason.EVIDENCE_SET_COMPLETE},
        applicability=other_scope,
    )
    result = _validate(decision)
    assert result.valid is False
    assert DerivEvidenceReviewReason.APPLICABILITY_MISMATCH in result.observed_reasons


def test_content_hash_mismatch_invalidates_decision() -> None:
    decision = _decision(
        DerivEvidenceDecisionState.APPROVED_FOR_PROOF_REVIEW,
        {DerivEvidenceReviewReason.EVIDENCE_SET_COMPLETE},
    )
    replacement = _artifact(content_hash="sha256:" + "b" * 64)
    result = _validate(decision, replacement)
    assert result.valid is False
    assert DerivEvidenceReviewReason.CONTENT_IDENTITY_MISMATCH in result.observed_reasons


def test_stale_decision_does_not_apply_to_replacement_evidence() -> None:
    decision = _decision(
        DerivEvidenceDecisionState.APPROVED_FOR_PROOF_REVIEW,
        {DerivEvidenceReviewReason.EVIDENCE_SET_COMPLETE},
    )
    original = _validate(decision, _artifact())
    replacement = _validate(
        decision, _artifact(content_hash="sha256:" + "c" * 64)
    )
    assert original.valid is True
    assert replacement.valid is False


def test_approved_decision_remains_non_authoritative() -> None:
    decision = _decision(
        DerivEvidenceDecisionState.APPROVED_FOR_PROOF_REVIEW,
        {DerivEvidenceReviewReason.EVIDENCE_SET_COMPLETE},
    )
    assert _validate(decision).valid is True
    assert not hasattr(decision, "to_proof")
    assert not hasattr(decision, "authorize")
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


def test_review_evaluation_constructs_no_gateway_or_network_connection() -> None:
    decision = _decision(
        DerivEvidenceDecisionState.APPROVED_FOR_PROOF_REVIEW,
        {DerivEvidenceReviewReason.EVIDENCE_SET_COMPLETE},
    )
    with patch("broker.deriv_gateway.DerivGateway") as gateway, patch(
        "broker.deriv_gateway.websockets.connect"
    ) as connect:
        assert _validate(decision).valid is True
    gateway.assert_not_called()
    connect.assert_not_called()


def test_review_evaluation_is_deterministic() -> None:
    decision = _decision(
        DerivEvidenceDecisionState.APPROVED_FOR_PROOF_REVIEW,
        {DerivEvidenceReviewReason.EVIDENCE_SET_COMPLETE},
    )
    registry = DerivEvidenceRegistry().register(_artifact())
    first = validate_deriv_evidence_review(decision, registry)
    second = validate_deriv_evidence_review(decision, registry)
    assert first == second
