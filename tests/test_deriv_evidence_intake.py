"""Offline-only tests for external Deriv evidence intake governance."""

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from broker.deriv_evidence import DerivEvidenceApplicability, DerivEvidenceClaimType
from broker.deriv_evidence_intake import (
    DerivClaimSupportState,
    DerivEvidenceClassification,
    DerivEvidenceCompleteness,
    DerivEvidenceContentType,
    DerivEvidenceProvenance,
    DerivEvidenceReadinessReason,
    DerivEvidenceReadinessState,
    DerivEvidenceRevocation,
    DerivEvidenceRevocationTarget,
    DerivEvidenceSourceType,
    DerivExternalEvidenceIntake,
    DerivNormalizedEvidenceField,
    DerivProvenanceConfidence,
    DerivSemanticClaimDeclaration,
    DerivSourceVerificationDecision,
    DerivSourceVerificationState,
    canonicalize_deriv_evidence_fields,
    extract_deriv_semantic_claims,
    sha256_material,
    validate_deriv_evidence_for_semantic_review,
)


_NOW = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)
_SCOPE = DerivEvidenceApplicability(
    broker="deriv",
    contract_family="OFFLINE_TEST_CONTRACT",
    symbol="OFFLINE_TEST_SYMBOL",
    account_currency="OFFLINE_TEST_CURRENCY",
    environment="offline-test-environment",
    quantity_basis="offline-test-quantity",
    stop_loss_semantic_id="offline:test:stop",
    multiplier_semantics_id="offline:test:multiplier",
    symbol_capability_scope="offline:test:scope",
)


def _fields(value="offline:test:value", unit="RATIO"):
    return (
        DerivNormalizedEvidenceField(
            "$.semantic.value", value, "offline:test:equation", unit
        ),
        DerivNormalizedEvidenceField(
            "$.semantic.rounding", "ROUND_HALF_EVEN:2", "offline:test:rounding"
        ),
        DerivNormalizedEvidenceField(
            "$.semantic.domain", "positive", "offline:test:domain"
        ),
    )


def _intake(
    *,
    intake_id="offline:test-only:intake-E1",
    classification=DerivEvidenceClassification.EXTERNAL_PRODUCTION_CANDIDATE,
    source_type=DerivEvidenceSourceType.CONTRACT_SPECIFICATION_CAPTURE,
    raw=b'{"offline":"externally-supplied-test-material"}',
    fields=None,
    completeness=DerivEvidenceCompleteness.COMPLETE,
    confidence=DerivProvenanceConfidence.DIRECT_EXTERNAL_SOURCE,
    applicability=_SCOPE,
    valid_until=None,
    source_identifier="offline:test-only:source-S1",
):
    fields = fields or _fields()
    provenance = DerivEvidenceProvenance(
        source_identifier,
        "offline:test-only:manual-supply",
        "offline:test-only:capture-actor",
        _NOW,
        sha256_material(raw),
        sha256_material(canonicalize_deriv_evidence_fields(fields)),
        applicability.environment,
        "offline:test-only:account-scope",
        confidence,
    )
    declarations = (
        DerivSemanticClaimDeclaration(
            "offline:test-only:claim-C1",
            DerivEvidenceClaimType.LOSS_MODEL_DESCRIPTION_IDENTITY,
            "offline:test:equation",
            fields[0].value,
            DerivClaimSupportState.SUPPORTED,
            tuple(field.path for field in fields),
            True,
        ),
    )
    return DerivExternalEvidenceIntake(
        1,
        intake_id,
        source_type,
        classification,
        _NOW,
        DerivEvidenceContentType.JSON,
        "offline:test-only:schema-v1",
        raw,
        fields,
        provenance,
        completeness,
        applicability,
        declarations,
        "Synthetic test harness only; not genuine production evidence",
        valid_until,
    )


def _verification(intake, **changes):
    values = {
        "verification_id": "offline:test-only:source-verification-V1",
        "intake_id": intake.intake_id,
        "raw_material_hash": intake.provenance.raw_material_hash,
        "normalized_material_hash": intake.provenance.normalized_material_hash,
        "source_identifier": intake.provenance.source_identifier,
        "classification": intake.classification,
        "applicability": intake.applicability,
        "state": DerivSourceVerificationState.VERIFIED_SOURCE,
        "verified_by": "offline:test-only:independent-source-reviewer",
        "verified_at": _NOW + timedelta(minutes=1),
    }
    values.update(changes)
    return DerivSourceVerificationDecision(**values)


def _validate(intakes, verifications=None, claims=None, **changes):
    verifications = (
        tuple(_verification(item) for item in intakes)
        if verifications is None
        else verifications
    )
    claims = (
        tuple(claim for item in intakes for claim in extract_deriv_semantic_claims(item))
        if claims is None
        else claims
    )
    return validate_deriv_evidence_for_semantic_review(
        intakes,
        verifications,
        claims,
        changes.pop("expected_applicability", _SCOPE),
        changes.pop("expected_account_scope", "offline:test-only:account-scope"),
        changes.pop("evaluation_at", _NOW + timedelta(minutes=2)),
        changes.pop("revocations", ()),
    )


def test_exact_intact_external_candidate_is_ready_for_advisory_review_only() -> None:
    intake = _intake()
    result = _validate((intake,))
    assert result.state is DerivEvidenceReadinessState.READY_FOR_SEMANTIC_REVIEW
    assert result.reason_codes == frozenset({DerivEvidenceReadinessReason.SOURCE_READY})


def test_no_production_evidence_has_controlled_placeholder_state() -> None:
    result = _validate((), verifications=(), claims=())
    assert result.state is DerivEvidenceReadinessState.PRODUCTION_EVIDENCE_NOT_AVAILABLE


def test_synthetic_classification_cannot_be_promoted() -> None:
    synthetic = _intake(
        classification=DerivEvidenceClassification.SYNTHETIC_TEST_ONLY,
        source_type=DerivEvidenceSourceType.SYNTHETIC_TEST_FIXTURE,
    )
    assert DerivEvidenceReadinessReason.SYNTHETIC_NOT_PRODUCTION in _validate(
        (synthetic,)
    ).reason_codes
    with pytest.raises(ValueError, match="classification"):
        replace(synthetic, classification=DerivEvidenceClassification.EXTERNAL_PRODUCTION_CANDIDATE)


def test_unverified_source_is_insufficient() -> None:
    intake = _intake()
    result = _validate((intake,), verifications=())
    assert result.state is DerivEvidenceReadinessState.INSUFFICIENT
    assert DerivEvidenceReadinessReason.SOURCE_NOT_VERIFIED in result.reason_codes


def test_changed_raw_material_or_normalization_is_rejected() -> None:
    intake = _intake()
    changed_raw = replace(intake, raw_material=b"changed")
    assert DerivEvidenceReadinessReason.MATERIAL_HASH_MISMATCH in _validate(
        (changed_raw,), verifications=(_verification(intake),)
    ).reason_codes
    changed_fields = replace(intake, normalized_fields=_fields("changed"))
    assert DerivEvidenceReadinessReason.NORMALIZATION_HASH_MISMATCH in _validate(
        (changed_fields,), verifications=(_verification(intake),)
    ).reason_codes


def test_verified_source_with_mismatched_hash_is_rejected() -> None:
    intake = _intake()
    verification = _verification(intake, raw_material_hash="sha256:" + "9" * 64)
    assert DerivEvidenceReadinessReason.MATERIAL_HASH_MISMATCH in _validate(
        (intake,), verifications=(verification,)
    ).reason_codes


def test_claim_from_e1_cannot_be_used_with_e2() -> None:
    e1 = _intake()
    e2 = _intake(intake_id="offline:test-only:intake-E2", raw=b"other")
    claims = extract_deriv_semantic_claims(e1)
    result = _validate((e2,), claims=claims)
    assert result.state is DerivEvidenceReadinessState.REJECTED
    assert DerivEvidenceReadinessReason.CLAIM_BINDING_MISMATCH in result.reason_codes


@pytest.mark.parametrize(
    "tamper_field,tamper_value",
    [
        ("raw_material_hash", "sha256:" + "7" * 64),
        ("normalized_material_hash", "sha256:" + "7" * 64),
        ("source_identifier", "offline:wrong-source"),
        ("claim_id", "offline:wrong-claim-id"),
        ("support_state", DerivClaimSupportState.NOT_ESTABLISHED),
    ],
)
def test_wrong_claim_binding_is_rejected(tamper_field, tamper_value) -> None:
    intake = _intake()
    claims = extract_deriv_semantic_claims(intake)
    tampered_claims = tuple(replace(c, **{tamper_field: tamper_value}) for c in claims)
    result = _validate((intake,), claims=tampered_claims)
    assert result.state is DerivEvidenceReadinessState.REJECTED
    assert DerivEvidenceReadinessReason.CLAIM_BINDING_MISMATCH in result.reason_codes


@pytest.mark.parametrize(
    "completeness",
    [DerivEvidenceCompleteness.PARTIAL, DerivEvidenceCompleteness.UNKNOWN],
)
def test_incomplete_source_cannot_support_complete_claim(completeness) -> None:
    intake = _intake(completeness=completeness)
    assert extract_deriv_semantic_claims(intake) == ()
    result = _validate((intake,))
    assert result.state is DerivEvidenceReadinessState.INSUFFICIENT
    assert DerivEvidenceReadinessReason.SOURCE_INCOMPLETE in result.reason_codes


def test_unknown_provenance_fails_closed() -> None:
    intake = _intake(confidence=DerivProvenanceConfidence.UNKNOWN)
    result = _validate((intake,))
    assert result.state is DerivEvidenceReadinessState.INSUFFICIENT
    assert DerivEvidenceReadinessReason.PROVENANCE_UNKNOWN in result.reason_codes


@pytest.mark.parametrize("change", [{"environment": "wrong"}, {"account_currency": "WRONG"}])
def test_wrong_environment_or_account_currency_fails_scope(change) -> None:
    wrong_scope = replace(_SCOPE, **change)
    intake = _intake(applicability=wrong_scope)
    assert DerivEvidenceReadinessReason.SCOPE_MISMATCH in _validate(
        (intake,)
    ).reason_codes


def test_wrong_account_scope_fails_closed() -> None:
    intake = _intake()
    changed = replace(
        intake,
        provenance=replace(intake.provenance, account_scope="offline:wrong-account"),
    )
    assert DerivEvidenceReadinessReason.SCOPE_MISMATCH in _validate(
        (changed,), verifications=(_verification(intake),)
    ).reason_codes


def test_conflicting_multi_artifact_pack_is_never_arbitrarily_selected() -> None:
    e1 = _intake()
    e2 = _intake(
        intake_id="offline:test-only:intake-E2",
        raw=b"other",
        fields=_fields("contradictory-value"),
        source_identifier="offline:test-only:source-S2",
    )
    result = _validate((e1, e2))
    assert result.state is DerivEvidenceReadinessState.CONFLICT
    assert DerivEvidenceReadinessReason.EVIDENCE_CONFLICT in result.reason_codes


@pytest.mark.parametrize(
    "target_kind,expected",
    [
        (DerivEvidenceRevocationTarget.INTAKE, DerivEvidenceReadinessReason.EVIDENCE_REVOKED),
        (DerivEvidenceRevocationTarget.SOURCE_VERIFICATION, DerivEvidenceReadinessReason.SOURCE_VERIFICATION_REVOKED),
    ],
)
def test_revocation_preserves_history_but_blocks_readiness(target_kind, expected) -> None:
    intake = _intake()
    verification = _verification(intake)
    target = intake.intake_id if target_kind is DerivEvidenceRevocationTarget.INTAKE else verification.verification_id
    revocation = DerivEvidenceRevocation(
        "offline:test-only:revocation-R1", target_kind, target, "offline test", _NOW
    )
    result = _validate(
        (intake,), verifications=(verification,), revocations=(revocation,)
    )
    assert expected in result.reason_codes
    assert intake.raw_material


def test_staleness_uses_explicit_evaluation_time() -> None:
    intake = _intake(valid_until=_NOW + timedelta(hours=1))
    result = _validate((intake,), evaluation_at=_NOW + timedelta(hours=2))
    assert DerivEvidenceReadinessReason.EVIDENCE_STALE in result.reason_codes


@pytest.mark.parametrize(
    "mutation",
    [
        "raw_hash", "normalized_hash", "source_id", "classification", "symbol",
        "environment", "contract_family", "quantity_basis", "stop", "multiplier",
        "currency", "equation", "operand_unit", "rounding", "domain",
    ],
)
def test_single_claim_relevant_tamper_fails_exact_binding(mutation) -> None:
    intake = _intake()
    verification = _verification(intake)
    if mutation == "raw_hash":
        intake = replace(intake, provenance=replace(intake.provenance, raw_material_hash="sha256:" + "8" * 64))
    elif mutation == "normalized_hash":
        intake = replace(intake, provenance=replace(intake.provenance, normalized_material_hash="sha256:" + "8" * 64))
    elif mutation == "source_id":
        intake = replace(intake, provenance=replace(intake.provenance, source_identifier="changed"))
    elif mutation == "classification":
        intake = replace(intake, source_type=DerivEvidenceSourceType.SYNTHETIC_TEST_FIXTURE, classification=DerivEvidenceClassification.SYNTHETIC_TEST_ONLY)
    elif mutation in {"symbol", "environment", "contract_family", "quantity_basis", "stop", "multiplier", "currency"}:
        field = {"stop": "stop_loss_semantic_id", "multiplier": "multiplier_semantics_id", "currency": "account_currency"}.get(mutation, mutation)
        scope = replace(intake.applicability, **{field: "changed"})
        intake = replace(intake, applicability=scope)
    else:
        index = {"equation": 0, "operand_unit": 0, "rounding": 1, "domain": 2}[mutation]
        fields = list(intake.normalized_fields)
        fields[index] = replace(fields[index], value="changed")
        intake = replace(intake, normalized_fields=tuple(fields))
    result = _validate((intake,), verifications=(verification,))
    assert result.state is not DerivEvidenceReadinessState.READY_FOR_SEMANTIC_REVIEW


def test_intake_models_are_immutable_and_structurally_isolated() -> None:
    intake = _intake()
    with pytest.raises(FrozenInstanceError):
        intake.intake_id = "changed"
    source = Path("broker/deriv_evidence_intake.py").read_text(encoding="utf-8")
    forbidden = (
        "requests.", "websockets", "deriv_gateway", "submit_order", "OrderRequest",
        "ExecutionIntent", "os.environ", "getenv(", "credential", "datetime.now",
        "evidence_to_proof", "verify_and_register", "evidence_to_quantity",
    )
    assert all(token not in source for token in forbidden)
