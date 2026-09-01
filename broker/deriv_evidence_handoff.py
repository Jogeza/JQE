"""Pure offline specification and validation for manual Deriv production evidence handoffs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import hashlib
import json
import re
from typing import Any

from broker.deriv_evidence import DerivEvidenceApplicability
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
    canonicalize_deriv_evidence_fields,
    sha256_material,
)


DERIV_EVIDENCE_HANDOFF_SCHEMA_VERSION = 1
_SHA256_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")


def _text(name: str, value: Any) -> None:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{name} must be a nonblank string")


def _time(name: str, value: Any) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _hash(name: str, value: Any) -> None:
    if type(value) is not str or not _SHA256_PATTERN.fullmatch(value):
        raise ValueError(f"{name} must be a lowercase SHA-256 ID")


class DerivEvidenceCategory(str, Enum):
    # Required by current financial semantics / proof specification
    EQUATION_IDENTITY = "EQUATION_IDENTITY"
    OPERAND_SEMANTICS = "OPERAND_SEMANTICS"
    QUANTITY_BASIS_SEMANTICS = "QUANTITY_BASIS_SEMANTICS"
    MULTIPLIER_SEMANTICS = "MULTIPLIER_SEMANTICS"
    STOP_LOSS_SEMANTICS = "STOP_LOSS_SEMANTICS"
    OUTPUT_LOSS_SEMANTICS = "OUTPUT_LOSS_SEMANTICS"
    ACCOUNT_CURRENCY_TREATMENT = "ACCOUNT_CURRENCY_TREATMENT"
    CONTRACT_FAMILY_SPECIFICATION = "CONTRACT_FAMILY_SPECIFICATION"
    FINANCIAL_ROUNDING_POLICY = "FINANCIAL_ROUNDING_POLICY"
    DOMAIN_CONSTRAINTS = "DOMAIN_CONSTRAINTS"

    # Supporting / Corroborating evidence categories
    OFFICIAL_SCHEMA_DOCUMENTATION = "OFFICIAL_SCHEMA_DOCUMENTATION"
    BROKER_PROPOSAL_CAPTURE = "BROKER_PROPOSAL_CAPTURE"
    BROKER_CONTRACTS_FOR_CAPTURE = "BROKER_CONTRACTS_FOR_CAPTURE"
    TRANSACTION_SETTLEMENT_RECORD = "TRANSACTION_SETTLEMENT_RECORD"
    MANUAL_BROKER_EXPORT = "MANUAL_BROKER_EXPORT"
    HISTORICAL_TICK_CAPTURE = "HISTORICAL_TICK_CAPTURE"


REQUIRED_DERIV_SEMANTIC_CATEGORIES: frozenset[DerivEvidenceCategory] = frozenset(
    {
        DerivEvidenceCategory.EQUATION_IDENTITY,
        DerivEvidenceCategory.OPERAND_SEMANTICS,
        DerivEvidenceCategory.QUANTITY_BASIS_SEMANTICS,
        DerivEvidenceCategory.MULTIPLIER_SEMANTICS,
        DerivEvidenceCategory.STOP_LOSS_SEMANTICS,
        DerivEvidenceCategory.OUTPUT_LOSS_SEMANTICS,
        DerivEvidenceCategory.ACCOUNT_CURRENCY_TREATMENT,
        DerivEvidenceCategory.CONTRACT_FAMILY_SPECIFICATION,
        DerivEvidenceCategory.FINANCIAL_ROUNDING_POLICY,
        DerivEvidenceCategory.DOMAIN_CONSTRAINTS,
    }
)


SUPPORTING_DERIV_EVIDENCE_CATEGORIES: frozenset[DerivEvidenceCategory] = frozenset(
    {
        DerivEvidenceCategory.OFFICIAL_SCHEMA_DOCUMENTATION,
        DerivEvidenceCategory.BROKER_PROPOSAL_CAPTURE,
        DerivEvidenceCategory.BROKER_CONTRACTS_FOR_CAPTURE,
        DerivEvidenceCategory.TRANSACTION_SETTLEMENT_RECORD,
        DerivEvidenceCategory.MANUAL_BROKER_EXPORT,
        DerivEvidenceCategory.HISTORICAL_TICK_CAPTURE,
    }
)


@dataclass(frozen=True, slots=True)
class DerivHandoffArtifactDescriptor:
    """Descriptor of an externally supplied file/artifact within a handoff package."""

    artifact_id: str
    category: DerivEvidenceCategory
    source_type: DerivEvidenceSourceType
    source_identifier: str
    content_type: DerivEvidenceContentType
    raw_material: bytes
    raw_material_hash: str
    capture_method: str
    completeness: DerivEvidenceCompleteness
    provenance_confidence: DerivProvenanceConfidence
    schema_or_content_version: str | None = None
    capture_actor_id: str | None = None
    observed_at: datetime | None = None
    environment: str | None = None
    account_scope: str | None = None
    account_currency: str | None = None
    contract_family: str | None = None
    symbol: str | None = None
    normalized_fields: tuple[DerivNormalizedEvidenceField, ...] = ()
    claim_declarations: tuple[DerivSemanticClaimDeclaration, ...] = ()

    def __post_init__(self) -> None:
        _text("artifact_id", self.artifact_id)
        if not isinstance(self.category, DerivEvidenceCategory):
            raise ValueError("category is invalid")
        if not isinstance(self.source_type, DerivEvidenceSourceType):
            raise ValueError("source_type is invalid")
        _text("source_identifier", self.source_identifier)
        if not isinstance(self.content_type, DerivEvidenceContentType):
            raise ValueError("content_type is invalid")
        if type(self.raw_material) is not bytes or not self.raw_material:
            raise ValueError("raw_material must be nonempty bytes")
        _hash("raw_material_hash", self.raw_material_hash)
        _text("capture_method", self.capture_method)
        if not isinstance(self.completeness, DerivEvidenceCompleteness):
            raise ValueError("completeness is invalid")
        if not isinstance(self.provenance_confidence, DerivProvenanceConfidence):
            raise ValueError("provenance_confidence is invalid")
        for name in (
            "schema_or_content_version",
            "capture_actor_id",
            "environment",
            "account_scope",
            "account_currency",
            "contract_family",
            "symbol",
        ):
            if getattr(self, name) is not None:
                _text(name, getattr(self, name))
        if self.observed_at is not None:
            _time("observed_at", self.observed_at)
        if type(self.normalized_fields) is not tuple or any(
            not isinstance(field, DerivNormalizedEvidenceField) for field in self.normalized_fields
        ):
            raise ValueError("normalized_fields must be an immutable tuple of DerivNormalizedEvidenceField")
        if self.normalized_fields:
            canonicalize_deriv_evidence_fields(self.normalized_fields)
        if type(self.claim_declarations) is not tuple or any(
            not isinstance(claim, DerivSemanticClaimDeclaration) for claim in self.claim_declarations
        ):
            raise ValueError("claim_declarations must be an immutable tuple of DerivSemanticClaimDeclaration")


def compute_handoff_package_id(
    broker: str,
    environment: str,
    classification: DerivEvidenceClassification,
    contract_family: str | None,
    account_currency: str | None,
    artifacts: tuple[DerivHandoffArtifactDescriptor, ...],
) -> str:
    """Compute deterministic SHA-256 bound identity for a handoff package."""
    ordered = sorted(artifacts, key=lambda a: a.artifact_id)
    summary = {
        "broker": broker,
        "environment": environment,
        "classification": classification.value,
        "contract_family": contract_family,
        "account_currency": account_currency,
        "artifacts": [
            {
                "artifact_id": a.artifact_id,
                "category": a.category.value,
                "source_identifier": a.source_identifier,
                "raw_material_hash": a.raw_material_hash,
                "completeness": a.completeness.value,
            }
            for a in ordered
        ],
    }
    encoded = json.dumps(summary, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "pkg:deriv:handoff:" + hashlib.sha256(encoded).hexdigest()[:32]


@dataclass(frozen=True, slots=True)
class DerivEvidenceHandoffPackage:
    """Immutable handoff container for externally supplied Deriv evidence."""

    schema_version: int
    package_id: str
    broker: str
    environment: str
    classification: DerivEvidenceClassification
    handed_off_at: datetime
    artifacts: tuple[DerivHandoffArtifactDescriptor, ...]
    contract_family: str | None = None
    account_currency: str | None = None
    account_scope: str | None = None
    symbol: str | None = None
    operator_notes: str | None = None

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != DERIV_EVIDENCE_HANDOFF_SCHEMA_VERSION:
            raise ValueError("unsupported evidence-handoff schema version")
        _text("package_id", self.package_id)
        _text("broker", self.broker)
        _text("environment", self.environment)
        if not isinstance(self.classification, DerivEvidenceClassification):
            raise ValueError("classification is invalid")
        _time("handed_off_at", self.handed_off_at)
        if type(self.artifacts) is not tuple or any(
            not isinstance(item, DerivHandoffArtifactDescriptor) for item in self.artifacts
        ):
            raise ValueError("artifacts must be an immutable tuple of DerivHandoffArtifactDescriptor")
        artifact_ids = tuple(a.artifact_id for a in self.artifacts)
        if len(artifact_ids) != len(set(artifact_ids)):
            raise ValueError("duplicate artifact IDs are not allowed in a handoff package")
        for name in ("contract_family", "account_currency", "account_scope", "symbol", "operator_notes"):
            if getattr(self, name) is not None:
                _text(name, getattr(self, name))


class DerivHandoffEligibilityState(str, Enum):
    ELIGIBLE_FOR_EVIDENCE_INTAKE = "ELIGIBLE_FOR_EVIDENCE_INTAKE"
    INSUFFICIENT = "INSUFFICIENT"
    REJECTED = "REJECTED"
    CONFLICT = "CONFLICT"


class DerivHandoffReasonCode(str, Enum):
    PACKAGE_ELIGIBLE = "PACKAGE_ELIGIBLE"
    SYNTHETIC_NOT_PRODUCTION = "SYNTHETIC_NOT_PRODUCTION"
    BROKER_MISMATCH = "BROKER_MISMATCH"
    ENVIRONMENT_MISMATCH = "ENVIRONMENT_MISMATCH"
    SCOPE_MISMATCH = "SCOPE_MISMATCH"
    CURRENCY_MISMATCH = "CURRENCY_MISMATCH"
    CONTRACT_FAMILY_MISMATCH = "CONTRACT_FAMILY_MISMATCH"
    MISSING_REQUIRED_CATEGORY = "MISSING_REQUIRED_CATEGORY"
    SOURCE_INCOMPLETE = "SOURCE_INCOMPLETE"
    RAW_MATERIAL_HASH_MISMATCH = "RAW_MATERIAL_HASH_MISMATCH"
    PROVENANCE_INCOMPLETE = "PROVENANCE_INCOMPLETE"
    DUPLICATE_ARTIFACT_IDENTITY = "DUPLICATE_ARTIFACT_IDENTITY"
    ARTIFACT_METADATA_CONFLICT = "ARTIFACT_METADATA_CONFLICT"
    PACKAGE_TAMPERED = "PACKAGE_TAMPERED"
    NO_ARTIFACTS_SUPPLIED = "NO_ARTIFACTS_SUPPLIED"


@dataclass(frozen=True, slots=True)
class DerivHandoffValidationResult:
    """Result of handoff package validation; never creates proof or authority."""

    state: DerivHandoffEligibilityState
    reason_codes: frozenset[DerivHandoffReasonCode]
    missing_required_categories: frozenset[DerivEvidenceCategory] = frozenset()
    covered_categories: frozenset[DerivEvidenceCategory] = frozenset()


def validate_deriv_production_evidence_handoff(
    package: DerivEvidenceHandoffPackage,
    expected_broker: str = "deriv",
    expected_environment: str | None = None,
    expected_contract_family: str | None = None,
    expected_account_currency: str | None = None,
    expected_account_scope: str | None = None,
    enforce_production_classification: bool = True,
    required_categories: frozenset[DerivEvidenceCategory] = REQUIRED_DERIV_SEMANTIC_CATEGORIES,
) -> DerivHandoffValidationResult:
    """Validate handoff package coverage and integrity before evidence intake."""
    if not isinstance(package, DerivEvidenceHandoffPackage):
        raise ValueError("package is invalid")

    reasons: set[DerivHandoffReasonCode] = set()

    if not package.artifacts:
        return DerivHandoffValidationResult(
            DerivHandoffEligibilityState.INSUFFICIENT,
            frozenset({DerivHandoffReasonCode.NO_ARTIFACTS_SUPPLIED}),
            missing_required_categories=required_categories,
            covered_categories=frozenset(),
        )

    # Validate package identity binding
    expected_pkg_id = compute_handoff_package_id(
        package.broker,
        package.environment,
        package.classification,
        package.contract_family,
        package.account_currency,
        package.artifacts,
    )
    if package.package_id != expected_pkg_id:
        reasons.add(DerivHandoffReasonCode.PACKAGE_TAMPERED)

    # Classification check
    if (
        enforce_production_classification
        and package.classification is not DerivEvidenceClassification.EXTERNAL_PRODUCTION_CANDIDATE
    ):
        reasons.add(DerivHandoffReasonCode.SYNTHETIC_NOT_PRODUCTION)

    # Scope checks against expectations
    if package.broker.lower() != expected_broker.lower():
        reasons.add(DerivHandoffReasonCode.BROKER_MISMATCH)

    if expected_environment is not None and package.environment != expected_environment:
        reasons.add(DerivHandoffReasonCode.ENVIRONMENT_MISMATCH)

    if expected_contract_family is not None and package.contract_family != expected_contract_family:
        reasons.add(DerivHandoffReasonCode.CONTRACT_FAMILY_MISMATCH)

    if expected_account_currency is not None and package.account_currency != expected_account_currency:
        reasons.add(DerivHandoffReasonCode.CURRENCY_MISMATCH)

    if expected_account_scope is not None and package.account_scope != expected_account_scope:
        reasons.add(DerivHandoffReasonCode.SCOPE_MISMATCH)

    # Evaluate individual artifacts
    covered: set[DerivEvidenceCategory] = set()
    artifact_hashes: dict[str, str] = {}
    artifact_envs: set[str] = set()
    artifact_currencies: set[str] = set()
    artifact_scopes: set[str] = set()
    artifact_families: set[str] = set()

    for artifact in package.artifacts:
        # Verify raw material hash integrity
        computed_hash = sha256_material(artifact.raw_material)
        if computed_hash != artifact.raw_material_hash:
            reasons.add(DerivHandoffReasonCode.RAW_MATERIAL_HASH_MISMATCH)

        # Track category
        covered.add(artifact.category)

        # Duplicate ID check with different hash
        if artifact.artifact_id in artifact_hashes:
            if artifact_hashes[artifact.artifact_id] != artifact.raw_material_hash:
                reasons.add(DerivHandoffReasonCode.DUPLICATE_ARTIFACT_IDENTITY)
        else:
            artifact_hashes[artifact.artifact_id] = artifact.raw_material_hash

        # Completeness
        if artifact.completeness is not DerivEvidenceCompleteness.COMPLETE:
            reasons.add(DerivHandoffReasonCode.SOURCE_INCOMPLETE)

        # Provenance confidence
        if artifact.provenance_confidence is DerivProvenanceConfidence.UNKNOWN:
            reasons.add(DerivHandoffReasonCode.PROVENANCE_INCOMPLETE)

        # Scope compatibility with package
        if artifact.environment is not None:
            artifact_envs.add(artifact.environment)
            if artifact.environment != package.environment:
                reasons.add(DerivHandoffReasonCode.ENVIRONMENT_MISMATCH)

        if artifact.account_currency is not None:
            artifact_currencies.add(artifact.account_currency)
            if package.account_currency is not None and artifact.account_currency != package.account_currency:
                reasons.add(DerivHandoffReasonCode.CURRENCY_MISMATCH)

        if artifact.account_scope is not None:
            artifact_scopes.add(artifact.account_scope)
            if package.account_scope is not None and artifact.account_scope != package.account_scope:
                reasons.add(DerivHandoffReasonCode.SCOPE_MISMATCH)

        if artifact.contract_family is not None:
            artifact_families.add(artifact.contract_family)
            if package.contract_family is not None and artifact.contract_family != package.contract_family:
                reasons.add(DerivHandoffReasonCode.CONTRACT_FAMILY_MISMATCH)

    # Check for intra-package conflicts
    if len(artifact_envs) > 1 or len(artifact_currencies) > 1 or len(artifact_scopes) > 1 or len(artifact_families) > 1:
        reasons.add(DerivHandoffReasonCode.ARTIFACT_METADATA_CONFLICT)

    # Coverage assessment
    missing_required = required_categories - covered
    if missing_required:
        reasons.add(DerivHandoffReasonCode.MISSING_REQUIRED_CATEGORY)

    if not reasons:
        return DerivHandoffValidationResult(
            DerivHandoffEligibilityState.ELIGIBLE_FOR_EVIDENCE_INTAKE,
            frozenset({DerivHandoffReasonCode.PACKAGE_ELIGIBLE}),
            missing_required_categories=frozenset(),
            covered_categories=frozenset(covered),
        )

    # Precise resolution of terminal state
    if DerivHandoffReasonCode.ARTIFACT_METADATA_CONFLICT in reasons:
        state = DerivHandoffEligibilityState.CONFLICT
    elif reasons <= {
        DerivHandoffReasonCode.MISSING_REQUIRED_CATEGORY,
        DerivHandoffReasonCode.SOURCE_INCOMPLETE,
        DerivHandoffReasonCode.PROVENANCE_INCOMPLETE,
        DerivHandoffReasonCode.NO_ARTIFACTS_SUPPLIED,
    }:
        state = DerivHandoffEligibilityState.INSUFFICIENT
    else:
        state = DerivHandoffEligibilityState.REJECTED

    return DerivHandoffValidationResult(
        state,
        frozenset(reasons),
        missing_required_categories=frozenset(missing_required),
        covered_categories=frozenset(covered),
    )


def build_candidate_intake_records_from_handoff(
    package: DerivEvidenceHandoffPackage,
) -> tuple[DerivExternalEvidenceIntake, ...]:
    """Convert an eligible handoff package into intake candidates without granting authority."""
    validation = validate_deriv_production_evidence_handoff(
        package,
        enforce_production_classification=False,
    )
    if validation.state is not DerivHandoffEligibilityState.ELIGIBLE_FOR_EVIDENCE_INTAKE:
        raise ValueError(f"cannot build intake records from ineligible handoff package: {validation.state.value}")

    records: list[DerivExternalEvidenceIntake] = []
    for artifact in package.artifacts:
        applicability = DerivEvidenceApplicability(
            broker=package.broker,
            contract_family=artifact.contract_family or package.contract_family,
            symbol=artifact.symbol or package.symbol,
            account_currency=artifact.account_currency or package.account_currency,
            environment=artifact.environment or package.environment,
        )
        provenance = DerivEvidenceProvenance(
            source_identifier=artifact.source_identifier,
            capture_method=artifact.capture_method,
            capture_actor_id=artifact.capture_actor_id,
            observed_at=artifact.observed_at or package.handed_off_at,
            raw_material_hash=artifact.raw_material_hash,
            normalized_material_hash=sha256_material(
                canonicalize_deriv_evidence_fields(artifact.normalized_fields)
            ),
            environment=artifact.environment or package.environment,
            account_scope=artifact.account_scope or package.account_scope,
            confidence=artifact.provenance_confidence,
        )
        records.append(
            DerivExternalEvidenceIntake(
                schema_version=1,
                intake_id=f"intake:{package.package_id}:{artifact.artifact_id}",
                source_type=artifact.source_type,
                classification=package.classification,
                captured_at=artifact.observed_at or package.handed_off_at,
                content_type=artifact.content_type,
                source_schema_id=artifact.schema_or_content_version,
                raw_material=artifact.raw_material,
                normalized_fields=artifact.normalized_fields,
                provenance=provenance,
                completeness=artifact.completeness,
                applicability=applicability,
                claim_declarations=artifact.claim_declarations,
                reviewer_notes=package.operator_notes,
            )
        )
    return tuple(records)
