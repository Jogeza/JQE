"""Offline tests for Deriv authoritative proof-registration governance."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime, timezone
from unittest.mock import patch

import pytest

from broker.deriv_contract_spec import (
    _AUTHORIZED_LOSS_MODEL_PROOFS,
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
from broker.deriv_proof_registration import (
    DERIV_PROOF_REGISTRATION_SCHEMA_VERSION,
    DerivAuthoritativeProofCandidate,
    DerivGovernanceRevocationReason,
    DerivGovernanceRevocationTarget,
    DerivIndependentVerificationDecision,
    DerivIndependentVerificationReason,
    DerivIndependentVerificationState,
    DerivProofGovernanceRevocation,
    DerivProofRegistrationEligibility,
    DerivProofRegistrationEligibilityState,
    DerivProofRegistrationReason,
    validate_deriv_proof_registration_eligibility,
)
from broker.deriv_proof_registry import (
    DerivProofAdmissionReason,
    DerivProofAdmissionRequest,
    DerivProofAdmissionState,
    DerivProofLookupReason,
    DerivProofLookupState,
    DerivProofRegistryState,
    admit_deriv_proof_registry_entry,
    lookup_deriv_proof_registry,
)
from broker.deriv_proof_review import (
    DerivProofReviewAssessment,
    DerivProofReviewReason,
    DerivProofReviewState,
)
from risk.position_sizing import authorize_execution_quantity


_ARTIFACT_ID = "offline:test-fixture:registration-artifact-A1"
_CLAIM_ID = "offline:test-fixture:registration-claim"
_DECISION_ID = "offline:test-fixture:registration-review-D1"
_ASSESSMENT_ID = "offline:test-fixture:registration-assessment-P1"
_CANDIDATE_ID = "offline:test-fixture:registration-candidate-C1"
_VERIFICATION_ID = "offline:test-fixture:independent-verification-V1"
_HASH_H1 = "sha256:" + "1" * 64
_MATERIAL_HASH = "sha256:" + "2" * 64
_VALID_FROM = datetime(2026, 9, 1, tzinfo=timezone.utc)
_VALID_UNTIL = datetime(2026, 12, 1, tzinfo=timezone.utc)
_SCOPE_P1 = DerivEvidenceApplicability(
    broker="deriv",
    contract_family="OFFLINE_TEST_CONTRACT",
    symbol="OFFLINE_TEST_SYMBOL",
    account_currency="OFFLINE_TEST_CURRENCY",
    environment="demo",
    quantity_basis="offline-test-quantity",
    stop_loss_semantic_id="offline:test-fixture:stop-v1",
    multiplier_semantics_id="offline:test-fixture:multiplier-v1",
    symbol_capability_scope="offline:test-fixture:scope-v1",
)


def _artifact(
    *,
    artifact_id=_ARTIFACT_ID,
    content_hash=_HASH_H1,
    claim_state=DerivEvidenceReviewState.REVIEWED,
):
    claim = DerivEvidenceClaim(
        claim_id=_CLAIM_ID,
        artifact_id=artifact_id,
        claim_type=DerivEvidenceClaimType.LOSS_MODEL_DESCRIPTION_IDENTITY,
        subject="synthetic offline proof material",
        value="non-financial test identity only",
        applicability=_SCOPE_P1,
        review_state=claim_state,
    )
    return DerivEvidenceArtifact(
        schema_version=1,
        artifact_id=artifact_id,
        source_identifier="offline:test-fixture:registration-source",
        source_title="Synthetic Offline Registration Governance Fixture",
        source_publisher="JQE tests",
        source_version="fixture-v1",
        recorded_date=date(2026, 9, 1),
        content_hash=content_hash,
        claims=(claim,),
        review_state=DerivEvidenceReviewState.REVIEWED,
    )


def _advisory_chain(
    decision_state=DerivEvidenceDecisionState.APPROVED_FOR_PROOF_REVIEW,
):
    if decision_state is DerivEvidenceDecisionState.APPROVED_FOR_PROOF_REVIEW:
        decision_reasons = frozenset({DerivEvidenceReviewReason.EVIDENCE_SET_COMPLETE})
        assessment_state = DerivProofReviewState.READY_FOR_AUTHORITATIVE_PROOF_REVIEW
        assessment_reasons = frozenset(
            {DerivProofReviewReason.REVIEW_PACKAGE_CONSISTENT}
        )
        claim_state = DerivEvidenceReviewState.REVIEWED
    elif decision_state is DerivEvidenceDecisionState.REJECTED:
        decision_reasons = frozenset({DerivEvidenceReviewReason.CLAIM_REJECTED})
        assessment_state = DerivProofReviewState.REJECTED
        assessment_reasons = frozenset(
            {
                DerivProofReviewReason.REVIEW_DECISION_NOT_APPROVED,
                DerivProofReviewReason.REVIEW_PACKAGE_CONFLICTING,
            }
        )
        claim_state = DerivEvidenceReviewState.REJECTED
    else:
        decision_reasons = frozenset({DerivEvidenceReviewReason.CLAIM_UNREVIEWED})
        assessment_state = DerivProofReviewState.INSUFFICIENT
        assessment_reasons = frozenset(
            {
                DerivProofReviewReason.REVIEW_DECISION_NOT_APPROVED,
                DerivProofReviewReason.REVIEW_SCOPE_INCOMPLETE,
            }
        )
        claim_state = DerivEvidenceReviewState.UNREVIEWED
    artifact = _artifact(claim_state=claim_state)
    decision = DerivEvidenceReviewDecision(
        schema_version=1,
        decision_id=_DECISION_ID,
        artifact_ids=(_ARTIFACT_ID,),
        artifact_content_hashes=(_HASH_H1,),
        claim_ids=(_CLAIM_ID,),
        state=decision_state,
        reason_codes=decision_reasons,
        reviewer_id="offline:test-fixture:advisory-reviewer",
        reviewed_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        applicability=_SCOPE_P1,
    )
    assessment = DerivProofReviewAssessment(
        schema_version=1,
        assessment_id=_ASSESSMENT_ID,
        review_decision_id=_DECISION_ID,
        artifact_ids=(_ARTIFACT_ID,),
        artifact_content_hashes=(_HASH_H1,),
        claim_ids=(_CLAIM_ID,),
        state=assessment_state,
        reason_codes=assessment_reasons,
        reviewer_id="offline:test-fixture:proof-reviewer",
        reviewed_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        applicability=_SCOPE_P1,
    )
    return artifact, decision, assessment


def _candidate(**changes):
    values = {
        "schema_version": DERIV_PROOF_REGISTRATION_SCHEMA_VERSION,
        "candidate_id": _CANDIDATE_ID,
        "candidate_material_hash": _MATERIAL_HASH,
        "loss_model_id": "offline:test-fixture:loss-model",
        "loss_model_version": 1,
        "evidence_source_id": "offline:test-fixture:source-identity",
        "source_assessment_id": _ASSESSMENT_ID,
        "review_decision_id": _DECISION_ID,
        "artifact_ids": (_ARTIFACT_ID,),
        "artifact_content_hashes": (_HASH_H1,),
        "claim_ids": (_CLAIM_ID,),
        "applicability": _SCOPE_P1,
        "valid_from": _VALID_FROM,
        "valid_until": _VALID_UNTIL,
    }
    values.update(changes)
    return DerivAuthoritativeProofCandidate(**values)


def _verification(
    state=DerivIndependentVerificationState.VERIFIED, **changes
):
    reasons = {
        DerivIndependentVerificationState.VERIFIED: frozenset(
            {DerivIndependentVerificationReason.CANDIDATE_INDEPENDENTLY_VERIFIED}
        ),
        DerivIndependentVerificationState.REJECTED: frozenset(
            {DerivIndependentVerificationReason.CANDIDATE_REJECTED}
        ),
        DerivIndependentVerificationState.INSUFFICIENT: frozenset(
            {DerivIndependentVerificationReason.VERIFICATION_SCOPE_INCOMPLETE}
        ),
    }
    values = {
        "schema_version": DERIV_PROOF_REGISTRATION_SCHEMA_VERSION,
        "verification_decision_id": _VERIFICATION_ID,
        "candidate_id": _CANDIDATE_ID,
        "candidate_material_hash": _MATERIAL_HASH,
        "loss_model_id": "offline:test-fixture:loss-model",
        "loss_model_version": 1,
        "evidence_source_id": "offline:test-fixture:source-identity",
        "source_assessment_id": _ASSESSMENT_ID,
        "review_decision_id": _DECISION_ID,
        "artifact_ids": (_ARTIFACT_ID,),
        "artifact_content_hashes": (_HASH_H1,),
        "claim_ids": (_CLAIM_ID,),
        "applicability": _SCOPE_P1,
        "valid_from": _VALID_FROM,
        "valid_until": _VALID_UNTIL,
        "state": state,
        "reason_codes": reasons.get(
            state,
            frozenset(
                {DerivIndependentVerificationReason.CANDIDATE_INDEPENDENTLY_VERIFIED}
            ),
        ),
        "verifier_id": "offline:test-fixture:independent-verifier",
        "verified_at": datetime(2026, 9, 1, tzinfo=timezone.utc),
        "rationale": "Synthetic independent governance fixture",
    }
    values.update(changes)
    return DerivIndependentVerificationDecision(**values)


def _revocation(target_kind, target_id, reason=DerivGovernanceRevocationReason.REVOKED):
    return DerivProofGovernanceRevocation(
        schema_version=1,
        revocation_id="offline:test-fixture:revocation-R1",
        target_kind=target_kind,
        target_id=target_id,
        reason=reason,
        revoked_by="offline:test-fixture:governance-reviewer",
        revoked_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        superseded_by_id=(
            "offline:test-fixture:replacement"
            if reason is DerivGovernanceRevocationReason.SUPERSEDED
            else None
        ),
    )


def _validate(candidate=None, verification=..., chain=None, artifact=None, revocations=()):
    source_artifact, decision, assessment = chain or _advisory_chain()
    registry = DerivEvidenceRegistry().register(artifact or source_artifact)
    return validate_deriv_proof_registration_eligibility(
        candidate or _candidate(),
        _verification() if verification is ... else verification,
        assessment,
        decision,
        registry,
        revocations,
    )


def _admission_request(**changes):
    values = {
        "schema_version": 1,
        "admission_id": "offline:test-fixture:admission-M1",
        "proof_id": "offline:test-fixture:proof-R1",
        "candidate_id": _CANDIDATE_ID,
        "candidate_material_hash": _MATERIAL_HASH,
        "verification_decision_id": _VERIFICATION_ID,
        "source_assessment_id": _ASSESSMENT_ID,
        "review_decision_id": _DECISION_ID,
        "artifact_ids": (_ARTIFACT_ID,),
        "artifact_content_hashes": (_HASH_H1,),
        "claim_ids": (_CLAIM_ID,),
        "applicability": _SCOPE_P1,
        "loss_model_id": "offline:test-fixture:loss-model",
        "loss_model_version": 1,
        "evidence_source_id": "offline:test-fixture:source-identity",
        "admitted_by": "offline:test-fixture:registry-reviewer",
        "admitted_at": datetime(2026, 9, 1, tzinfo=timezone.utc),
        "valid_from": _VALID_FROM,
        "valid_until": _VALID_UNTIL,
    }
    values.update(changes)
    return DerivProofAdmissionRequest(**values)


def _admission_bundle(
    *, candidate=None, verification=None, chain=None, artifact=None, revocations=()
):
    source_artifact, decision, assessment = chain or _advisory_chain()
    evidence_registry = DerivEvidenceRegistry().register(artifact or source_artifact)
    candidate = candidate or _candidate()
    verification = verification or _verification()
    eligibility = validate_deriv_proof_registration_eligibility(
        candidate,
        verification,
        assessment,
        decision,
        evidence_registry,
        revocations,
    )
    return (
        eligibility,
        candidate,
        verification,
        assessment,
        decision,
        evidence_registry,
    )


def _admit(
    registry=None,
    request=None,
    bundle=None,
    eligibility=None,
    revocations=(),
):
    bundle = bundle or _admission_bundle(revocations=revocations)
    current_eligibility, candidate, verification, assessment, decision, evidence = bundle
    return admit_deriv_proof_registry_entry(
        registry or DerivProofRegistryState(),
        request or _admission_request(),
        current_eligibility if eligibility is None else eligibility,
        candidate,
        verification,
        assessment,
        decision,
        evidence,
        revocations,
    )


@pytest.mark.parametrize(
    "field,value",
    [("environment", None), ("environment", "offline"), ("account_currency", None)],
)
def test_financial_authority_requires_environment_and_currency(field, value) -> None:
    applicability = replace(_SCOPE_P1, **{field: value})
    with pytest.raises(ValueError, match=field):
        _candidate(applicability=applicability)


@pytest.mark.parametrize(
    "valid_from,valid_until",
    [(_VALID_UNTIL, _VALID_FROM), (_VALID_FROM, _VALID_FROM)],
)
def test_candidate_requires_ordered_validity_window(valid_from, valid_until) -> None:
    with pytest.raises(ValueError, match="valid_until"):
        _candidate(valid_from=valid_from, valid_until=valid_until)


def test_exact_current_chain_is_eligible_for_registration_governance() -> None:
    result = _validate()
    assert result.state is DerivProofRegistrationEligibilityState.ELIGIBLE_FOR_REGISTRATION
    assert result.reason_codes == frozenset(
        {DerivProofRegistrationReason.REGISTRATION_CHAIN_COMPLETE}
    )


def test_missing_independent_verification_is_ineligible() -> None:
    result = _validate(verification=None)
    assert not result.eligible
    assert DerivProofRegistrationReason.INDEPENDENT_VERIFICATION_MISSING in result.reason_codes


@pytest.mark.parametrize(
    "state",
    [
        DerivIndependentVerificationState.REJECTED,
        DerivIndependentVerificationState.INSUFFICIENT,
    ],
)
def test_nonverified_independent_decision_is_ineligible(state) -> None:
    result = _validate(verification=_verification(state))
    assert not result.eligible
    assert (
        DerivProofRegistrationReason.INDEPENDENT_VERIFICATION_NOT_VERIFIED
        in result.reason_codes
    )


@pytest.mark.parametrize(
    "state",
    [DerivEvidenceDecisionState.REJECTED, DerivEvidenceDecisionState.INSUFFICIENT],
)
def test_nonready_advisory_assessment_is_ineligible(state) -> None:
    result = _validate(chain=_advisory_chain(state))
    assert not result.eligible
    assert DerivProofRegistrationReason.SOURCE_ASSESSMENT_NOT_READY in result.reason_codes
    assert DerivProofRegistrationReason.ADVISORY_DECISION_NOT_APPROVED in result.reason_codes


def test_same_artifact_with_changed_hash_invalidates_full_chain() -> None:
    result = _validate(artifact=_artifact(content_hash="sha256:" + "3" * 64))
    assert not result.eligible
    assert DerivProofRegistrationReason.SOURCE_ASSESSMENT_INVALID in result.reason_codes


def test_replacement_artifact_cannot_inherit_A1_verification() -> None:
    result = _validate(artifact=_artifact(artifact_id="offline:test-fixture:artifact-A2"))
    assert not result.eligible
    assert DerivProofRegistrationReason.SOURCE_ASSESSMENT_INVALID in result.reason_codes


def test_candidate_substitution_cannot_inherit_C1_verification() -> None:
    candidate = _candidate(candidate_id="offline:test-fixture:candidate-C2")
    result = _validate(candidate=candidate)
    assert not result.eligible
    assert (
        DerivProofRegistrationReason.INDEPENDENT_VERIFICATION_MISMATCH
        in result.reason_codes
    )


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("source_assessment_id", "offline:test-fixture:other-assessment", DerivProofRegistrationReason.CANDIDATE_IDENTITY_MISMATCH),
        ("review_decision_id", "offline:test-fixture:other-decision", DerivProofRegistrationReason.CANDIDATE_IDENTITY_MISMATCH),
        ("artifact_ids", ("offline:test-fixture:artifact-A2",), DerivProofRegistrationReason.EVIDENCE_IDENTITY_MISMATCH),
        ("artifact_content_hashes", ("sha256:" + "4" * 64,), DerivProofRegistrationReason.EVIDENCE_IDENTITY_MISMATCH),
        ("claim_ids", ("offline:test-fixture:other-claim",), DerivProofRegistrationReason.CLAIM_SET_MISMATCH),
    ],
)
def test_candidate_must_bind_exact_advisory_chain(field, value, reason) -> None:
    result = _validate(candidate=_candidate(**{field: value}))
    assert not result.eligible
    assert reason in result.reason_codes


@pytest.mark.parametrize(
    "field",
    [
        "contract_family",
        "symbol",
        "quantity_basis",
        "stop_loss_semantic_id",
        "multiplier_semantics_id",
        "symbol_capability_scope",
    ],
)
def test_every_authority_scope_dimension_is_exact(field) -> None:
    scope_p2 = replace(_SCOPE_P1, **{field: "offline:test-fixture:scope-P2"})
    result = _validate(candidate=_candidate(applicability=scope_p2))
    assert not result.eligible
    assert DerivProofRegistrationReason.APPLICABILITY_MISMATCH in result.reason_codes


def test_verification_applicability_cannot_retarget_candidate() -> None:
    scope_p2 = replace(_SCOPE_P1, symbol="OFFLINE_TEST_SYMBOL_P2")
    result = _validate(verification=_verification(applicability=scope_p2))
    assert not result.eligible
    assert DerivProofRegistrationReason.APPLICABILITY_MISMATCH in result.reason_codes


@pytest.mark.parametrize(
    "field,value",
    [
        ("candidate_id", "offline:test-fixture:candidate-C2"),
        ("candidate_material_hash", "sha256:" + "5" * 64),
        ("loss_model_id", "offline:test-fixture:other-model"),
        ("loss_model_version", 2),
        ("evidence_source_id", "offline:test-fixture:other-source"),
        ("source_assessment_id", "offline:test-fixture:other-assessment"),
        ("review_decision_id", "offline:test-fixture:other-decision"),
        ("artifact_ids", ("offline:test-fixture:artifact-A2",)),
        ("artifact_content_hashes", ("sha256:" + "6" * 64,)),
        ("claim_ids", ("offline:test-fixture:other-claim",)),
    ],
)
def test_verification_must_bind_every_candidate_identity(field, value) -> None:
    result = _validate(verification=_verification(**{field: value}))
    assert not result.eligible
    assert (
        DerivProofRegistrationReason.INDEPENDENT_VERIFICATION_MISMATCH
        in result.reason_codes
    )


def test_revoked_candidate_is_ineligible() -> None:
    record = _revocation(DerivGovernanceRevocationTarget.CANDIDATE, _CANDIDATE_ID)
    result = _validate(revocations=(record,))
    assert not result.eligible
    assert DerivProofRegistrationReason.CANDIDATE_REVOKED in result.reason_codes


@pytest.mark.parametrize(
    "reason",
    [DerivGovernanceRevocationReason.REVOKED, DerivGovernanceRevocationReason.SUPERSEDED],
)
def test_revoked_or_superseded_verification_is_ineligible(reason) -> None:
    record = _revocation(
        DerivGovernanceRevocationTarget.INDEPENDENT_VERIFICATION,
        _VERIFICATION_ID,
        reason,
    )
    result = _validate(revocations=(record,))
    assert not result.eligible
    assert (
        DerivProofRegistrationReason.INDEPENDENT_VERIFICATION_REVOKED
        in result.reason_codes
    )


def test_duplicate_revocation_identity_fails_closed() -> None:
    record = _revocation(DerivGovernanceRevocationTarget.CANDIDATE, "other-candidate")
    result = _validate(revocations=(record, record))
    assert not result.eligible
    assert DerivProofRegistrationReason.REVOCATION_RECORD_CONFLICT in result.reason_codes


@pytest.mark.parametrize("schema", [True, False, 1.0, "1", None])
def test_candidate_schema_version_is_strict(schema) -> None:
    with pytest.raises(ValueError, match="strict integer"):
        _candidate(schema_version=schema)


def test_future_candidate_schema_is_rejected() -> None:
    with pytest.raises(ValueError, match="unsupported"):
        _candidate(schema_version=2)


@pytest.mark.parametrize(
    "field,value",
    [
        ("candidate_id", ""),
        ("source_assessment_id", "   "),
        ("review_decision_id", None),
        ("loss_model_id", 1),
        ("evidence_source_id", ""),
    ],
)
def test_candidate_identity_fields_are_strict(field, value) -> None:
    with pytest.raises(ValueError, match="nonblank string"):
        _candidate(**{field: value})


@pytest.mark.parametrize(
    "field,value",
    [
        ("verification_decision_id", ""),
        ("candidate_id", None),
        ("verifier_id", "   "),
    ],
)
def test_verification_identity_fields_are_strict(field, value) -> None:
    with pytest.raises(ValueError, match="nonblank string"):
        _verification(**{field: value})


def test_verification_state_and_reasons_are_strict() -> None:
    with pytest.raises(ValueError, match="verification state"):
        _verification(state="VERIFIED")
    with pytest.raises(ValueError, match="do not match"):
        _verification(reason_codes=frozenset({DerivIndependentVerificationReason.CANDIDATE_REJECTED}))


def test_verification_requires_nonempty_evidence_binding() -> None:
    with pytest.raises(ValueError, match="at least one artifact"):
        _verification(artifact_ids=(), artifact_content_hashes=())
    with pytest.raises(ValueError, match="at least one claim"):
        _verification(claim_ids=())


def test_eligibility_result_state_and_reasons_are_strict() -> None:
    with pytest.raises(ValueError, match="eligibility state"):
        DerivProofRegistrationEligibility(
            "ELIGIBLE_FOR_REGISTRATION",
            frozenset({DerivProofRegistrationReason.REGISTRATION_CHAIN_COMPLETE}),
        )
    with pytest.raises(ValueError, match="eligible result"):
        DerivProofRegistrationEligibility(
            DerivProofRegistrationEligibilityState.ELIGIBLE_FOR_REGISTRATION,
            frozenset({DerivProofRegistrationReason.CANDIDATE_REVOKED}),
        )


@pytest.mark.parametrize("verified_at", [datetime(2026, 9, 1), "2026-09-01", None])
def test_verification_timestamp_must_be_timezone_aware(verified_at) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        _verification(verified_at=verified_at)


@pytest.mark.parametrize("value", ["sha256:abc", "sha1:" + "a" * 40, "sha256:" + "A" * 64])
def test_candidate_material_hash_is_canonical(value) -> None:
    with pytest.raises(ValueError, match="sha256"):
        _candidate(candidate_material_hash=value)


def test_authority_models_and_result_are_immutable() -> None:
    candidate = _candidate()
    verification = _verification()
    revocation = _revocation(DerivGovernanceRevocationTarget.CANDIDATE, _CANDIDATE_ID)
    result = _validate()
    for obj, name in (
        (candidate, "candidate_id"),
        (verification, "verifier_id"),
        (revocation, "target_id"),
        (result, "state"),
    ):
        with pytest.raises(FrozenInstanceError):
            setattr(obj, name, "changed")


def test_validation_is_pure_and_deterministic() -> None:
    candidate = _candidate()
    verification = _verification()
    artifact, decision, assessment = _advisory_chain()
    registry = DerivEvidenceRegistry().register(artifact)
    first = validate_deriv_proof_registration_eligibility(
        candidate, verification, assessment, decision, registry
    )
    second = validate_deriv_proof_registration_eligibility(
        candidate, verification, assessment, decision, registry
    )
    assert first == second


def test_governance_has_no_proof_conversion_or_registry_admission_api() -> None:
    candidate = _candidate()
    result = _validate()
    for obj in (candidate, result):
        for name in (
            "to_proof",
            "make_proof",
            "register",
            "register_proof",
            "authorize",
            "enable_capability",
        ):
            assert not hasattr(obj, name)
    assert len(_AUTHORIZED_LOSS_MODEL_PROOFS) == 0


def test_eligible_governance_result_grants_no_quantity_authority() -> None:
    assert _validate().eligible
    capability = evaluate_deriv_quantity_capability(
        current_deriv_multiplier_specification()
    )
    sizing = authorize_execution_quantity(
        broker="deriv",
        balance=10_000,
        risk_percent=0.5,
        entry=100,
        stop_loss=92,
    )
    assert len(_AUTHORIZED_LOSS_MODEL_PROOFS) == 0
    assert capability.stop_risk_authorizable is False
    assert sizing.quantity is None
    assert sizing.risk_verifiable is False


def test_governance_constructs_no_gateway_or_network_connection() -> None:
    with patch("broker.deriv_gateway.DerivGateway") as gateway, patch(
        "broker.deriv_gateway.websockets.connect"
    ) as connect:
        assert _validate().eligible
    gateway.assert_not_called()
    connect.assert_not_called()


def test_valid_exact_admission_creates_new_isolated_immutable_state() -> None:
    original = DerivProofRegistryState()
    outcome = _admit(registry=original)
    assert outcome.result.state is DerivProofAdmissionState.ADMITTED
    assert outcome.result.reason_codes == frozenset(
        {DerivProofAdmissionReason.ADMISSION_ACCEPTED}
    )
    assert original.entries == ()
    assert len(outcome.registry.entries) == 1
    assert outcome.result.entry is outcome.registry.entries[0]


def test_exact_repeated_admission_is_idempotent() -> None:
    first = _admit()
    second = _admit(registry=first.registry)
    assert second.result.state is DerivProofAdmissionState.ALREADY_ADMITTED
    assert second.result.reason_codes == frozenset(
        {DerivProofAdmissionReason.EXACT_DUPLICATE}
    )
    assert second.registry is first.registry
    assert len(second.registry.entries) == 1


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("candidate_material_hash", "sha256:" + "7" * 64, DerivProofAdmissionReason.MATERIAL_HASH_MISMATCH),
        ("applicability", replace(_SCOPE_P1, symbol="OFFLINE_TEST_SYMBOL_P2"), DerivProofAdmissionReason.APPLICABILITY_MISMATCH),
        ("verification_decision_id", "offline:test-fixture:verification-V2", DerivProofAdmissionReason.VERIFICATION_MISMATCH),
        ("source_assessment_id", "offline:test-fixture:assessment-P2", DerivProofAdmissionReason.ADVISORY_CHAIN_MISMATCH),
        ("artifact_content_hashes", ("sha256:" + "8" * 64,), DerivProofAdmissionReason.EVIDENCE_IDENTITY_MISMATCH),
        ("loss_model_version", 2, DerivProofAdmissionReason.LOSS_MODEL_IDENTITY_MISMATCH),
    ],
)
def test_same_proof_id_with_changed_authority_material_is_rejected(
    field, value, reason
) -> None:
    first = _admit()
    outcome = _admit(
        registry=first.registry,
        request=_admission_request(**{field: value}),
    )
    assert outcome.result.state is DerivProofAdmissionState.REJECTED
    assert reason in outcome.result.reason_codes
    assert DerivProofAdmissionReason.PROOF_ID_CONFLICT in outcome.result.reason_codes
    assert outcome.registry is first.registry


def test_same_proof_id_with_different_verified_lineage_is_rejected() -> None:
    first = _admit()
    verification_v2 = _verification(
        verification_decision_id="offline:test-fixture:verification-V2"
    )
    bundle_v2 = _admission_bundle(verification=verification_v2)
    outcome = _admit(
        registry=first.registry,
        request=_admission_request(
            verification_decision_id=verification_v2.verification_decision_id
        ),
        bundle=bundle_v2,
    )
    assert outcome.result.state is DerivProofAdmissionState.REJECTED
    assert DerivProofAdmissionReason.PROOF_ID_CONFLICT in outcome.result.reason_codes


def test_same_proof_id_with_different_advisory_lineage_is_rejected() -> None:
    first = _admit()
    artifact, decision, assessment = _advisory_chain()
    assessment_p2 = replace(
        assessment, assessment_id="offline:test-fixture:assessment-P2"
    )
    candidate_p2 = _candidate(source_assessment_id=assessment_p2.assessment_id)
    verification_p2 = _verification(source_assessment_id=assessment_p2.assessment_id)
    bundle_p2 = _admission_bundle(
        chain=(artifact, decision, assessment_p2),
        candidate=candidate_p2,
        verification=verification_p2,
    )
    outcome = _admit(
        registry=first.registry,
        request=_admission_request(source_assessment_id=assessment_p2.assessment_id),
        bundle=bundle_p2,
    )
    assert outcome.result.state is DerivProofAdmissionState.REJECTED
    assert DerivProofAdmissionReason.PROOF_ID_CONFLICT in outcome.result.reason_codes


def test_forged_eligible_enum_cannot_bypass_full_chain_revalidation() -> None:
    artifact, decision, assessment = _advisory_chain()
    stale_artifact = replace(artifact, content_hash="sha256:" + "9" * 64)
    candidate = _candidate()
    verification = _verification()
    stale_registry = DerivEvidenceRegistry().register(stale_artifact)
    stale_bundle = (
        validate_deriv_proof_registration_eligibility(
            candidate, verification, assessment, decision, stale_registry
        ),
        candidate,
        verification,
        assessment,
        decision,
        stale_registry,
    )
    forged = DerivProofRegistrationEligibility(
        DerivProofRegistrationEligibilityState.ELIGIBLE_FOR_REGISTRATION,
        frozenset({DerivProofRegistrationReason.REGISTRATION_CHAIN_COMPLETE}),
    )
    outcome = _admit(bundle=stale_bundle, eligibility=forged)
    assert outcome.result.state is DerivProofAdmissionState.REJECTED
    assert DerivProofAdmissionReason.ELIGIBILITY_STALE in outcome.result.reason_codes
    assert outcome.registry.entries == ()


def test_explicitly_ineligible_result_cannot_be_admitted() -> None:
    ineligible = DerivProofRegistrationEligibility(
        DerivProofRegistrationEligibilityState.INELIGIBLE,
        frozenset({DerivProofRegistrationReason.CANDIDATE_REVOKED}),
    )
    outcome = _admit(eligibility=ineligible)
    assert outcome.result.state is DerivProofAdmissionState.REJECTED
    assert DerivProofAdmissionReason.ELIGIBILITY_INVALID in outcome.result.reason_codes
    assert DerivProofAdmissionReason.ELIGIBILITY_STALE in outcome.result.reason_codes


def test_artifact_hash_changed_after_eligibility_is_rejected() -> None:
    eligibility, candidate, verification, assessment, decision, _ = _admission_bundle()
    stale_evidence = DerivEvidenceRegistry().register(
        _artifact(content_hash="sha256:" + "a" * 64)
    )
    stale_bundle = (
        eligibility,
        candidate,
        verification,
        assessment,
        decision,
        stale_evidence,
    )
    outcome = _admit(bundle=stale_bundle, eligibility=eligibility)
    assert outcome.result.state is DerivProofAdmissionState.REJECTED
    assert DerivProofAdmissionReason.ELIGIBILITY_STALE in outcome.result.reason_codes


def test_claim_changed_after_eligibility_is_rejected() -> None:
    eligibility, candidate, verification, assessment, decision, _ = _admission_bundle()
    artifact = _artifact()
    changed_claim = replace(
        artifact.claims[0], claim_id="offline:test-fixture:replacement-claim"
    )
    stale_evidence = DerivEvidenceRegistry().register(
        replace(artifact, claims=(changed_claim,))
    )
    stale_bundle = (
        eligibility,
        candidate,
        verification,
        assessment,
        decision,
        stale_evidence,
    )
    outcome = _admit(bundle=stale_bundle, eligibility=eligibility)
    assert outcome.result.state is DerivProofAdmissionState.REJECTED
    assert DerivProofAdmissionReason.ELIGIBILITY_STALE in outcome.result.reason_codes


@pytest.mark.parametrize(
    "target_kind,target_id,reason,expected",
    [
        (DerivGovernanceRevocationTarget.CANDIDATE, _CANDIDATE_ID, DerivGovernanceRevocationReason.REVOKED, DerivProofAdmissionReason.CANDIDATE_REVOKED),
        (DerivGovernanceRevocationTarget.INDEPENDENT_VERIFICATION, _VERIFICATION_ID, DerivGovernanceRevocationReason.REVOKED, DerivProofAdmissionReason.VERIFICATION_REVOKED),
        (DerivGovernanceRevocationTarget.INDEPENDENT_VERIFICATION, _VERIFICATION_ID, DerivGovernanceRevocationReason.SUPERSEDED, DerivProofAdmissionReason.VERIFICATION_SUPERSEDED),
        (DerivGovernanceRevocationTarget.REGISTERED_PROOF, "offline:test-fixture:proof-R1", DerivGovernanceRevocationReason.REVOKED, DerivProofAdmissionReason.PROOF_REVOKED),
    ],
)
def test_revocation_or_supersession_prevents_admission(
    target_kind, target_id, reason, expected
) -> None:
    record = _revocation(target_kind, target_id, reason)
    bundle = _admission_bundle(revocations=(record,))
    outcome = _admit(bundle=bundle, revocations=(record,))
    assert outcome.result.state is DerivProofAdmissionState.REJECTED
    assert expected in outcome.result.reason_codes
    assert outcome.registry.entries == ()


def test_conflicting_revocation_records_prevent_admission() -> None:
    record = _revocation(
        DerivGovernanceRevocationTarget.CANDIDATE,
        "offline:test-fixture:unrelated-candidate",
    )
    bundle = _admission_bundle(revocations=(record, record))
    outcome = _admit(bundle=bundle, revocations=(record, record))
    assert outcome.result.state is DerivProofAdmissionState.REJECTED
    assert (
        DerivProofAdmissionReason.REVOCATION_RECORD_CONFLICT
        in outcome.result.reason_codes
    )


def test_registered_proof_revocation_retains_history_but_disables_active_lookup() -> None:
    admitted = _admit()
    record = _revocation(
        DerivGovernanceRevocationTarget.REGISTERED_PROOF,
        "offline:test-fixture:proof-R1",
    )
    lookup = lookup_deriv_proof_registry(admitted.registry, _SCOPE_P1, (record,))
    assert lookup.state is DerivProofLookupState.REVOKED_ENTRY
    assert lookup.reason_codes == frozenset({DerivProofLookupReason.ENTRY_REVOKED})
    assert lookup.entry is admitted.registry.entries[0]
    assert admitted.registry.get_historical("offline:test-fixture:proof-R1") is lookup.entry
    assert len(admitted.registry.entries) == 1


def test_lookup_requires_exact_applicability_without_widening() -> None:
    admitted = _admit()
    exact = lookup_deriv_proof_registry(admitted.registry, _SCOPE_P1)
    other = lookup_deriv_proof_registry(
        admitted.registry,
        replace(_SCOPE_P1, symbol="OFFLINE_TEST_SYMBOL_P2"),
    )
    assert exact.state is DerivProofLookupState.ACTIVE_ENTRY_FOUND
    assert exact.reason_codes == frozenset(
        {DerivProofLookupReason.EXACT_ACTIVE_ENTRY}
    )
    assert other.state is DerivProofLookupState.NO_ENTRY
    assert other.entry is None


def test_lookup_fails_closed_for_multiple_exact_entries() -> None:
    admitted = _admit()
    first = admitted.registry.entries[0]
    second = replace(
        first,
        proof_id="offline:test-fixture:proof-R2",
        admission_id="offline:test-fixture:admission-M2",
        candidate_id="offline:test-fixture:candidate-C2",
    )
    state = DerivProofRegistryState(tuple(sorted((first, second), key=lambda x: x.proof_id)))
    lookup = lookup_deriv_proof_registry(state, _SCOPE_P1)
    assert lookup.state is DerivProofLookupState.CONFLICTING_STATE
    assert DerivProofLookupReason.MULTIPLE_EXACT_ENTRIES in lookup.reason_codes


def test_registry_models_are_immutable_and_deterministically_ordered() -> None:
    admitted = _admit()
    with pytest.raises(FrozenInstanceError):
        admitted.registry.entries = ()
    with pytest.raises(FrozenInstanceError):
        admitted.registry.entries[0].proof_id = "changed"
    with pytest.raises(ValueError, match="deterministic"):
        first = admitted.registry.entries[0]
        DerivProofRegistryState(
            (
                replace(first, proof_id="z", admission_id="z", candidate_id="z"),
                replace(first, proof_id="a", admission_id="a", candidate_id="a"),
            )
        )


def test_registry_state_rejects_duplicate_stable_identities() -> None:
    entry = _admit().registry.entries[0]
    with pytest.raises(ValueError, match="duplicate proof ID"):
        DerivProofRegistryState((entry, entry))


@pytest.mark.parametrize("schema", [True, 1.0, "1", None, 2])
def test_admission_request_schema_is_strict(schema) -> None:
    with pytest.raises(ValueError, match="schema_version|unsupported"):
        _admission_request(schema_version=schema)


def test_admission_request_rejects_malformed_identity_and_hash() -> None:
    with pytest.raises(ValueError, match="nonblank"):
        _admission_request(proof_id="   ")
    with pytest.raises(ValueError, match="sha256"):
        _admission_request(candidate_material_hash="sha256:bad")


def test_isolated_registry_never_mutates_canonical_authority_or_quantity() -> None:
    admitted = _admit()
    assert len(admitted.registry.entries) == 1
    assert len(_AUTHORIZED_LOSS_MODEL_PROOFS) == 0
    capability = evaluate_deriv_quantity_capability(
        current_deriv_multiplier_specification()
    )
    sizing = authorize_execution_quantity(
        broker="deriv", balance=10_000, risk_percent=0.5, entry=100, stop_loss=92
    )
    assert capability.stop_risk_authorizable is False
    assert sizing.quantity is None
    assert sizing.risk_verifiable is False


def test_registry_admission_and_lookup_construct_no_gateway_or_network() -> None:
    with patch("broker.deriv_gateway.DerivGateway") as gateway, patch(
        "broker.deriv_gateway.websockets.connect"
    ) as connect:
        admitted = _admit()
        lookup = lookup_deriv_proof_registry(admitted.registry, _SCOPE_P1)
        assert lookup.state is DerivProofLookupState.ACTIVE_ENTRY_FOUND
    gateway.assert_not_called()
    connect.assert_not_called()
