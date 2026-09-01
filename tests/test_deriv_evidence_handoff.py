"""Offline-only unit tests for Deriv production evidence handoff specification."""

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from broker.deriv_evidence import DerivEvidenceApplicability, DerivEvidenceClaimType
from broker.deriv_evidence_handoff import (
    DERIV_EVIDENCE_HANDOFF_SCHEMA_VERSION,
    REQUIRED_DERIV_SEMANTIC_CATEGORIES,
    SUPPORTING_DERIV_EVIDENCE_CATEGORIES,
    DerivEvidenceCategory,
    DerivEvidenceHandoffPackage,
    DerivHandoffArtifactDescriptor,
    DerivHandoffEligibilityState,
    DerivHandoffReasonCode,
    build_candidate_intake_records_from_handoff,
    compute_handoff_package_id,
    validate_deriv_production_evidence_handoff,
)
from broker.deriv_evidence_intake import (
    DerivClaimSupportState,
    DerivEvidenceClassification,
    DerivEvidenceCompleteness,
    DerivEvidenceContentType,
    DerivEvidenceProvenance,
    DerivEvidenceSourceType,
    DerivExternalEvidenceIntake,
    DerivNormalizedEvidenceField,
    DerivProvenanceConfidence,
    DerivSemanticClaimDeclaration,
    sha256_material,
)


_NOW = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)
_ENV = "offline-test-environment"
_CURRENCY = "USD"
_SCOPE = "offline-test-account-scope"
_FAMILY = "MULTUP"


_CATEGORY_TO_CLAIM_TYPE = {
    DerivEvidenceCategory.EQUATION_IDENTITY: DerivEvidenceClaimType.LOSS_MODEL_DESCRIPTION_IDENTITY,
    DerivEvidenceCategory.OPERAND_SEMANTICS: DerivEvidenceClaimType.LOSS_MODEL_DESCRIPTION_IDENTITY,
    DerivEvidenceCategory.QUANTITY_BASIS_SEMANTICS: DerivEvidenceClaimType.QUANTITY_BASIS_SEMANTICS,
    DerivEvidenceCategory.MULTIPLIER_SEMANTICS: DerivEvidenceClaimType.MULTIPLIER_SEMANTICS,
    DerivEvidenceCategory.STOP_LOSS_SEMANTICS: DerivEvidenceClaimType.STOP_LOSS_SEMANTICS,
    DerivEvidenceCategory.OUTPUT_LOSS_SEMANTICS: DerivEvidenceClaimType.LOSS_MODEL_DESCRIPTION_IDENTITY,
    DerivEvidenceCategory.ACCOUNT_CURRENCY_TREATMENT: DerivEvidenceClaimType.CURRENCY_SEMANTICS,
    DerivEvidenceCategory.CONTRACT_FAMILY_SPECIFICATION: DerivEvidenceClaimType.CONTRACT_FAMILY_AVAILABILITY,
    DerivEvidenceCategory.FINANCIAL_ROUNDING_POLICY: DerivEvidenceClaimType.LOSS_MODEL_DESCRIPTION_IDENTITY,
    DerivEvidenceCategory.DOMAIN_CONSTRAINTS: DerivEvidenceClaimType.LOSS_MODEL_DESCRIPTION_IDENTITY,
    DerivEvidenceCategory.OFFICIAL_SCHEMA_DOCUMENTATION: DerivEvidenceClaimType.CONTRACT_FAMILY_AVAILABILITY,
    DerivEvidenceCategory.BROKER_PROPOSAL_CAPTURE: DerivEvidenceClaimType.CONTRACT_FAMILY_AVAILABILITY,
    DerivEvidenceCategory.BROKER_CONTRACTS_FOR_CAPTURE: DerivEvidenceClaimType.CONTRACT_FAMILY_AVAILABILITY,
    DerivEvidenceCategory.TRANSACTION_SETTLEMENT_RECORD: DerivEvidenceClaimType.LOSS_MODEL_DESCRIPTION_IDENTITY,
    DerivEvidenceCategory.MANUAL_BROKER_EXPORT: DerivEvidenceClaimType.LOSS_MODEL_DESCRIPTION_IDENTITY,
    DerivEvidenceCategory.HISTORICAL_TICK_CAPTURE: DerivEvidenceClaimType.LOSS_MODEL_DESCRIPTION_IDENTITY,
}


def _artifact(
    category: DerivEvidenceCategory,
    artifact_id: str | None = None,
    raw_material: bytes = b'{"offline":"test-evidence"}',
    completeness: DerivEvidenceCompleteness = DerivEvidenceCompleteness.COMPLETE,
    confidence: DerivProvenanceConfidence = DerivProvenanceConfidence.DIRECT_EXTERNAL_SOURCE,
    environment: str = _ENV,
    currency: str = _CURRENCY,
    account_scope: str = _SCOPE,
    contract_family: str = _FAMILY,
) -> DerivHandoffArtifactDescriptor:
    aid = artifact_id or f"art:{category.value.lower()}"
    claim_type = _CATEGORY_TO_CLAIM_TYPE.get(category, DerivEvidenceClaimType.LOSS_MODEL_DESCRIPTION_IDENTITY)
    return DerivHandoffArtifactDescriptor(
        artifact_id=aid,
        category=category,
        source_type=DerivEvidenceSourceType.CONTRACT_SPECIFICATION_CAPTURE,
        source_identifier=f"source:{category.value.lower()}",
        content_type=DerivEvidenceContentType.JSON,
        raw_material=raw_material,
        raw_material_hash=sha256_material(raw_material),
        capture_method="manual-export",
        completeness=completeness,
        provenance_confidence=confidence,
        schema_or_content_version="v1.0",
        capture_actor_id="reviewer-1",
        observed_at=_NOW,
        environment=environment,
        account_scope=account_scope,
        account_currency=currency,
        contract_family=contract_family,
        symbol="R_100",
        normalized_fields=(
            DerivNormalizedEvidenceField(
                path=f"$.semantic.{category.value.lower()}",
                value="test-value",
                semantic_id=f"sem:{category.value.lower()}",
            ),
        ),
        claim_declarations=(
            DerivSemanticClaimDeclaration(
                claim_id=f"claim:{category.value.lower()}",
                claim_type=claim_type,
                semantic_id=f"sem:{category.value.lower()}",
                value="test-value",
                support_state=DerivClaimSupportState.SUPPORTED,
                source_field_paths=(f"$.semantic.{category.value.lower()}",),
                requires_complete_source=True,
            ),
        ),
    )


def _all_required_artifacts() -> tuple[DerivHandoffArtifactDescriptor, ...]:
    return tuple(_artifact(cat) for cat in sorted(REQUIRED_DERIV_SEMANTIC_CATEGORIES, key=lambda c: c.value))


def _package(
    artifacts: tuple[DerivHandoffArtifactDescriptor, ...] | None = None,
    classification: DerivEvidenceClassification = DerivEvidenceClassification.EXTERNAL_PRODUCTION_CANDIDATE,
    broker: str = "deriv",
    environment: str = _ENV,
    currency: str = _CURRENCY,
    account_scope: str = _SCOPE,
    contract_family: str = _FAMILY,
) -> DerivEvidenceHandoffPackage:
    arts = artifacts if artifacts is not None else _all_required_artifacts()
    pkg_id = compute_handoff_package_id(
        broker=broker,
        environment=environment,
        classification=classification,
        contract_family=contract_family,
        account_currency=currency,
        artifacts=arts,
    )
    return DerivEvidenceHandoffPackage(
        schema_version=DERIV_EVIDENCE_HANDOFF_SCHEMA_VERSION,
        package_id=pkg_id,
        broker=broker,
        environment=environment,
        classification=classification,
        handed_off_at=_NOW,
        artifacts=arts,
        contract_family=contract_family,
        account_currency=currency,
        account_scope=account_scope,
        symbol="R_100",
        operator_notes="Verified test handoff package",
    )


def test_valid_production_candidate_handoff_is_eligible_for_intake() -> None:
    pkg = _package()
    result = validate_deriv_production_evidence_handoff(
        pkg,
        expected_environment=_ENV,
        expected_contract_family=_FAMILY,
        expected_account_currency=_CURRENCY,
        expected_account_scope=_SCOPE,
    )
    assert result.state is DerivHandoffEligibilityState.ELIGIBLE_FOR_EVIDENCE_INTAKE
    assert result.reason_codes == frozenset({DerivHandoffReasonCode.PACKAGE_ELIGIBLE})
    assert result.missing_required_categories == frozenset()
    assert result.covered_categories >= REQUIRED_DERIV_SEMANTIC_CATEGORIES


def test_synthetic_fixture_presented_as_production_is_rejected() -> None:
    pkg = _package(classification=DerivEvidenceClassification.SYNTHETIC_TEST_ONLY)
    result = validate_deriv_production_evidence_handoff(pkg)
    assert result.state is DerivHandoffEligibilityState.REJECTED
    assert DerivHandoffReasonCode.SYNTHETIC_NOT_PRODUCTION in result.reason_codes


def test_synthetic_fixture_can_be_validated_with_flag() -> None:
    pkg = _package(classification=DerivEvidenceClassification.SYNTHETIC_TEST_ONLY)
    result = validate_deriv_production_evidence_handoff(
        pkg,
        enforce_production_classification=False,
    )
    assert result.state is DerivHandoffEligibilityState.ELIGIBLE_FOR_EVIDENCE_INTAKE


def test_missing_required_category_is_insufficient() -> None:
    # Omit one required category (e.g. EQUATION_IDENTITY)
    subset = tuple(
        _artifact(cat)
        for cat in sorted(REQUIRED_DERIV_SEMANTIC_CATEGORIES, key=lambda c: c.value)
        if cat is not DerivEvidenceCategory.EQUATION_IDENTITY
    )
    pkg = _package(artifacts=subset)
    result = validate_deriv_production_evidence_handoff(pkg)
    assert result.state is DerivHandoffEligibilityState.INSUFFICIENT
    assert DerivHandoffReasonCode.MISSING_REQUIRED_CATEGORY in result.reason_codes
    assert DerivEvidenceCategory.EQUATION_IDENTITY in result.missing_required_categories


def test_missing_optional_supporting_material_does_not_fail() -> None:
    # All required are present, no supporting categories added
    pkg = _package()
    result = validate_deriv_production_evidence_handoff(pkg)
    assert result.state is DerivHandoffEligibilityState.ELIGIBLE_FOR_EVIDENCE_INTAKE


def test_supporting_material_can_be_included() -> None:
    arts = _all_required_artifacts() + (_artifact(DerivEvidenceCategory.OFFICIAL_SCHEMA_DOCUMENTATION),)
    pkg = _package(artifacts=arts)
    result = validate_deriv_production_evidence_handoff(pkg)
    assert result.state is DerivHandoffEligibilityState.ELIGIBLE_FOR_EVIDENCE_INTAKE
    assert DerivEvidenceCategory.OFFICIAL_SCHEMA_DOCUMENTATION in result.covered_categories


def test_incomplete_artifact_is_insufficient() -> None:
    arts = list(_all_required_artifacts())
    arts[0] = replace(arts[0], completeness=DerivEvidenceCompleteness.PARTIAL)
    pkg = _package(artifacts=tuple(arts))
    result = validate_deriv_production_evidence_handoff(pkg)
    assert result.state is DerivHandoffEligibilityState.INSUFFICIENT
    assert DerivHandoffReasonCode.SOURCE_INCOMPLETE in result.reason_codes


def test_unknown_provenance_is_insufficient() -> None:
    arts = list(_all_required_artifacts())
    arts[0] = replace(arts[0], provenance_confidence=DerivProvenanceConfidence.UNKNOWN)
    pkg = _package(artifacts=tuple(arts))
    result = validate_deriv_production_evidence_handoff(pkg)
    assert result.state is DerivHandoffEligibilityState.INSUFFICIENT
    assert DerivHandoffReasonCode.PROVENANCE_INCOMPLETE in result.reason_codes


def test_empty_artifacts_is_insufficient() -> None:
    pkg = _package(artifacts=())
    result = validate_deriv_production_evidence_handoff(pkg)
    assert result.state is DerivHandoffEligibilityState.INSUFFICIENT
    assert DerivHandoffReasonCode.NO_ARTIFACTS_SUPPLIED in result.reason_codes


@pytest.mark.parametrize(
    "tamper_field,expected_reason",
    [
        ("broker", DerivHandoffReasonCode.BROKER_MISMATCH),
        ("environment", DerivHandoffReasonCode.ENVIRONMENT_MISMATCH),
        ("contract_family", DerivHandoffReasonCode.CONTRACT_FAMILY_MISMATCH),
        ("account_currency", DerivHandoffReasonCode.CURRENCY_MISMATCH),
        ("account_scope", DerivHandoffReasonCode.SCOPE_MISMATCH),
    ],
)
def test_wrong_scope_is_rejected(tamper_field, expected_reason) -> None:
    pkg = _package()
    kwargs = {
        "expected_broker": "deriv",
        "expected_environment": _ENV,
        "expected_contract_family": _FAMILY,
        "expected_account_currency": _CURRENCY,
        "expected_account_scope": _SCOPE,
    }
    kwargs[f"expected_{tamper_field}"] = "WRONG_VALUE"
    result = validate_deriv_production_evidence_handoff(pkg, **kwargs)
    assert result.state is DerivHandoffEligibilityState.REJECTED
    assert expected_reason in result.reason_codes


def test_tampered_raw_hash_is_rejected() -> None:
    arts = list(_all_required_artifacts())
    arts[0] = replace(arts[0], raw_material_hash="sha256:" + "0" * 64)
    # create package with tampered artifact
    pkg = _package(artifacts=tuple(arts))
    result = validate_deriv_production_evidence_handoff(pkg)
    assert result.state is DerivHandoffEligibilityState.REJECTED
    assert DerivHandoffReasonCode.RAW_MATERIAL_HASH_MISMATCH in result.reason_codes


def test_tampered_package_id_is_rejected() -> None:
    pkg = _package()
    tampered_pkg = replace(pkg, package_id="pkg:deriv:handoff:tampered1234567890")
    result = validate_deriv_production_evidence_handoff(tampered_pkg)
    assert result.state is DerivHandoffEligibilityState.REJECTED
    assert DerivHandoffReasonCode.PACKAGE_TAMPERED in result.reason_codes


def test_unknown_completeness_is_insufficient() -> None:
    arts = list(_all_required_artifacts())
    arts[0] = replace(arts[0], completeness=DerivEvidenceCompleteness.UNKNOWN)
    pkg = _package(artifacts=tuple(arts))
    result = validate_deriv_production_evidence_handoff(pkg)
    assert result.state is DerivHandoffEligibilityState.INSUFFICIENT
    assert DerivHandoffReasonCode.SOURCE_INCOMPLETE in result.reason_codes


def test_conflicting_artifact_currencies_produces_conflict() -> None:
    arts = list(_all_required_artifacts())
    arts[0] = replace(arts[0], account_currency="EUR")
    arts[1] = replace(arts[1], account_currency="USD")
    pkg = _package(artifacts=tuple(arts))
    result = validate_deriv_production_evidence_handoff(pkg)
    assert result.state is DerivHandoffEligibilityState.CONFLICT
    assert DerivHandoffReasonCode.ARTIFACT_METADATA_CONFLICT in result.reason_codes


def test_conflicting_artifact_environments_produces_conflict() -> None:
    arts = list(_all_required_artifacts())
    arts[0] = replace(arts[0], environment="production")
    arts[1] = replace(arts[1], environment="demo")
    pkg = _package(artifacts=tuple(arts))
    result = validate_deriv_production_evidence_handoff(pkg)
    assert result.state is DerivHandoffEligibilityState.CONFLICT
    assert DerivHandoffReasonCode.ARTIFACT_METADATA_CONFLICT in result.reason_codes


def test_conflicting_artifact_contract_families_produces_conflict() -> None:
    arts = list(_all_required_artifacts())
    arts[0] = replace(arts[0], contract_family="MULTUP")
    arts[1] = replace(arts[1], contract_family="MULTDOWN")
    pkg = _package(artifacts=tuple(arts))
    result = validate_deriv_production_evidence_handoff(pkg)
    assert result.state is DerivHandoffEligibilityState.CONFLICT
    assert DerivHandoffReasonCode.ARTIFACT_METADATA_CONFLICT in result.reason_codes


def test_conflicting_artifact_account_scopes_produces_conflict() -> None:
    arts = list(_all_required_artifacts())
    arts[0] = replace(arts[0], account_scope="scope-A")
    arts[1] = replace(arts[1], account_scope="scope-B")
    pkg = _package(artifacts=tuple(arts))
    result = validate_deriv_production_evidence_handoff(pkg)
    assert result.state is DerivHandoffEligibilityState.CONFLICT
    assert DerivHandoffReasonCode.ARTIFACT_METADATA_CONFLICT in result.reason_codes


def test_duplicate_artifact_id_in_package_raises() -> None:
    art = _artifact(DerivEvidenceCategory.EQUATION_IDENTITY, artifact_id="art:dup")
    with pytest.raises(ValueError, match="duplicate artifact IDs"):
        _package(artifacts=(art, art))


def test_deterministic_package_id_independent_of_input_order() -> None:
    arts = _all_required_artifacts()
    reversed_arts = tuple(reversed(arts))
    id1 = compute_handoff_package_id("deriv", _ENV, DerivEvidenceClassification.EXTERNAL_PRODUCTION_CANDIDATE, _FAMILY, _CURRENCY, arts)
    id2 = compute_handoff_package_id("deriv", _ENV, DerivEvidenceClassification.EXTERNAL_PRODUCTION_CANDIDATE, _FAMILY, _CURRENCY, reversed_arts)
    assert id1 == id2


def test_changed_artifact_changes_package_id() -> None:
    arts1 = _all_required_artifacts()
    arts2 = list(arts1)
    arts2[0] = replace(arts2[0], raw_material=b'{"different":"data"}', raw_material_hash=sha256_material(b'{"different":"data"}'))
    id1 = compute_handoff_package_id("deriv", _ENV, DerivEvidenceClassification.EXTERNAL_PRODUCTION_CANDIDATE, _FAMILY, _CURRENCY, arts1)
    id2 = compute_handoff_package_id("deriv", _ENV, DerivEvidenceClassification.EXTERNAL_PRODUCTION_CANDIDATE, _FAMILY, _CURRENCY, tuple(arts2))
    assert id1 != id2


def test_models_are_immutable() -> None:
    pkg = _package()
    with pytest.raises(FrozenInstanceError):
        pkg.package_id = "changed"
    art = _artifact(DerivEvidenceCategory.EQUATION_IDENTITY)
    with pytest.raises(FrozenInstanceError):
        art.artifact_id = "changed"


def test_conversion_helper_generates_intake_records() -> None:
    pkg = _package()
    intake_records = build_candidate_intake_records_from_handoff(pkg)
    assert len(intake_records) == len(pkg.artifacts)
    assert all(isinstance(r, DerivExternalEvidenceIntake) for r in intake_records)
    assert all(r.classification == pkg.classification for r in intake_records)


def test_conversion_helper_rejects_ineligible_package() -> None:
    pkg = _package(artifacts=())
    with pytest.raises(ValueError, match="ineligible"):
        build_candidate_intake_records_from_handoff(pkg)


def test_structural_isolation_and_no_forbidden_tokens() -> None:
    source = Path("broker/deriv_evidence_handoff.py").read_text(encoding="utf-8")
    forbidden = (
        "requests.", "websockets", "deriv_gateway", "submit_order", "OrderRequest",
        "ExecutionIntent", "os.environ", "getenv(", "credential", "datetime.now",
        "evidence_to_proof", "verify_and_register", "evidence_to_quantity",
        "DerivGateway", "MT5Gateway",
    )
    assert all(token not in source for token in forbidden)
