"""Pure external Deriv evidence intake and source-verification governance."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import hashlib
import json
import re
from typing import Any

from broker.deriv_evidence import DerivEvidenceApplicability, DerivEvidenceClaimType


DERIV_EVIDENCE_INTAKE_SCHEMA_VERSION = 1
_SHA256_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")


def _text(name: str, value: Any) -> None:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{name} must be a nonblank string")


def _hash(name: str, value: Any) -> None:
    if type(value) is not str or not _SHA256_PATTERN.fullmatch(value):
        raise ValueError(f"{name} must be a lowercase SHA-256 ID")


def _time(name: str, value: Any) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


class DerivEvidenceSourceType(str, Enum):
    OFFICIAL_SCHEMA_DOCUMENTATION = "OFFICIAL_SCHEMA_DOCUMENTATION"
    BROKER_RESPONSE_CAPTURE = "BROKER_RESPONSE_CAPTURE"
    CONTRACT_SPECIFICATION_CAPTURE = "CONTRACT_SPECIFICATION_CAPTURE"
    PROPOSAL_RESPONSE_CAPTURE = "PROPOSAL_RESPONSE_CAPTURE"
    TRANSACTION_SETTLEMENT_RECORD = "TRANSACTION_SETTLEMENT_RECORD"
    MANUAL_BROKER_EXPORT = "MANUAL_BROKER_EXPORT"
    SYNTHETIC_TEST_FIXTURE = "SYNTHETIC_TEST_FIXTURE"


class DerivEvidenceClassification(str, Enum):
    SYNTHETIC_TEST_ONLY = "SYNTHETIC_TEST_ONLY"
    EXTERNAL_PRODUCTION_CANDIDATE = "EXTERNAL_PRODUCTION_CANDIDATE"


class DerivEvidenceContentType(str, Enum):
    JSON = "JSON"
    DOCUMENT = "DOCUMENT"
    BINARY = "BINARY"
    TABULAR_EXPORT = "TABULAR_EXPORT"


class DerivEvidenceCompleteness(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"


class DerivProvenanceConfidence(str, Enum):
    DIRECT_EXTERNAL_SOURCE = "DIRECT_EXTERNAL_SOURCE"
    REVIEWER_ATTESTED = "REVIEWER_ATTESTED"
    UNKNOWN = "UNKNOWN"


class DerivClaimSupportState(str, Enum):
    SUPPORTED = "SUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    NOT_ESTABLISHED = "NOT_ESTABLISHED"


@dataclass(frozen=True, slots=True)
class DerivNormalizedEvidenceField:
    path: str
    value: str
    semantic_id: str
    unit_id: str | None = None

    def __post_init__(self) -> None:
        for name in ("path", "value", "semantic_id"):
            _text(name, getattr(self, name))
        if self.unit_id is not None:
            _text("unit_id", self.unit_id)


def canonicalize_deriv_evidence_fields(
    fields: tuple[DerivNormalizedEvidenceField, ...],
) -> bytes:
    """Canonically encode explicit fields without inferring or converting values."""
    if type(fields) is not tuple or any(
        not isinstance(field, DerivNormalizedEvidenceField) for field in fields
    ):
        raise ValueError("fields must be an immutable typed tuple")
    paths = tuple(field.path for field in fields)
    if len(paths) != len(set(paths)):
        raise ValueError("duplicate normalized field paths are not allowed")
    ordered = sorted(fields, key=lambda field: field.path)
    payload = [
        {
            "path": field.path,
            "semantic_id": field.semantic_id,
            "unit_id": field.unit_id,
            "value": field.value,
        }
        for field in ordered
    ]
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def sha256_material(material: bytes) -> str:
    if type(material) is not bytes:
        raise ValueError("material must be bytes")
    return "sha256:" + hashlib.sha256(material).hexdigest()


@dataclass(frozen=True, slots=True)
class DerivEvidenceProvenance:
    source_identifier: str
    capture_method: str
    capture_actor_id: str | None
    observed_at: datetime | None
    raw_material_hash: str
    normalized_material_hash: str
    environment: str | None
    account_scope: str | None
    confidence: DerivProvenanceConfidence

    def __post_init__(self) -> None:
        _text("source_identifier", self.source_identifier)
        _text("capture_method", self.capture_method)
        if self.capture_actor_id is not None:
            _text("capture_actor_id", self.capture_actor_id)
        if self.observed_at is not None:
            _time("observed_at", self.observed_at)
        _hash("raw_material_hash", self.raw_material_hash)
        _hash("normalized_material_hash", self.normalized_material_hash)
        for name in ("environment", "account_scope"):
            if getattr(self, name) is not None:
                _text(name, getattr(self, name))
        if not isinstance(self.confidence, DerivProvenanceConfidence):
            raise ValueError("provenance confidence is invalid")


@dataclass(frozen=True, slots=True)
class DerivSemanticClaimDeclaration:
    claim_id: str
    claim_type: DerivEvidenceClaimType
    semantic_id: str
    value: str
    support_state: DerivClaimSupportState
    source_field_paths: tuple[str, ...]
    requires_complete_source: bool

    def __post_init__(self) -> None:
        for name in ("claim_id", "semantic_id", "value"):
            _text(name, getattr(self, name))
        if not isinstance(self.claim_type, DerivEvidenceClaimType):
            raise ValueError("claim type is invalid")
        if not isinstance(self.support_state, DerivClaimSupportState):
            raise ValueError("claim support state is invalid")
        if type(self.source_field_paths) is not tuple or not self.source_field_paths or any(
            type(path) is not str or not path.strip() for path in self.source_field_paths
        ):
            raise ValueError("claim source paths must be a nonempty immutable tuple")
        if len(self.source_field_paths) != len(set(self.source_field_paths)):
            raise ValueError("duplicate claim source paths are not allowed")
        if type(self.requires_complete_source) is not bool:
            raise ValueError("requires_complete_source must be boolean")


@dataclass(frozen=True, slots=True)
class DerivExternalEvidenceIntake:
    schema_version: int
    intake_id: str
    source_type: DerivEvidenceSourceType
    classification: DerivEvidenceClassification
    captured_at: datetime
    content_type: DerivEvidenceContentType
    source_schema_id: str | None
    raw_material: bytes
    normalized_fields: tuple[DerivNormalizedEvidenceField, ...]
    provenance: DerivEvidenceProvenance
    completeness: DerivEvidenceCompleteness
    applicability: DerivEvidenceApplicability
    claim_declarations: tuple[DerivSemanticClaimDeclaration, ...]
    reviewer_notes: str | None = None
    valid_until: datetime | None = None

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("unsupported evidence-intake schema version")
        _text("intake_id", self.intake_id)
        if not isinstance(self.source_type, DerivEvidenceSourceType):
            raise ValueError("source type is invalid")
        if not isinstance(self.classification, DerivEvidenceClassification):
            raise ValueError("classification is invalid")
        if (
            self.source_type is DerivEvidenceSourceType.SYNTHETIC_TEST_FIXTURE
        ) != (
            self.classification is DerivEvidenceClassification.SYNTHETIC_TEST_ONLY
        ):
            raise ValueError("synthetic source classification cannot be changed")
        _time("captured_at", self.captured_at)
        if not isinstance(self.content_type, DerivEvidenceContentType):
            raise ValueError("content type is invalid")
        if self.source_schema_id is not None:
            _text("source_schema_id", self.source_schema_id)
        if type(self.raw_material) is not bytes or not self.raw_material:
            raise ValueError("raw_material must be nonempty bytes")
        canonicalize_deriv_evidence_fields(self.normalized_fields)
        if not isinstance(self.provenance, DerivEvidenceProvenance):
            raise ValueError("provenance is invalid")
        if not isinstance(self.completeness, DerivEvidenceCompleteness):
            raise ValueError("completeness is invalid")
        if not isinstance(self.applicability, DerivEvidenceApplicability):
            raise ValueError("applicability is invalid")
        if type(self.claim_declarations) is not tuple or any(
            not isinstance(claim, DerivSemanticClaimDeclaration)
            for claim in self.claim_declarations
        ):
            raise ValueError("claim declarations must be an immutable typed tuple")
        claim_ids = tuple(claim.claim_id for claim in self.claim_declarations)
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("duplicate claim IDs are not allowed")
        if self.reviewer_notes is not None:
            _text("reviewer_notes", self.reviewer_notes)
        if self.valid_until is not None:
            _time("valid_until", self.valid_until)
            if self.valid_until <= self.captured_at:
                raise ValueError("valid_until must follow captured_at")


@dataclass(frozen=True, slots=True)
class DerivExtractedEvidenceClaim:
    claim_id: str
    intake_id: str
    raw_material_hash: str
    normalized_material_hash: str
    source_identifier: str
    classification: DerivEvidenceClassification
    claim_type: DerivEvidenceClaimType
    semantic_id: str
    value: str
    support_state: DerivClaimSupportState
    applicability: DerivEvidenceApplicability
    source_field_paths: tuple[str, ...]


def extract_deriv_semantic_claims(
    intake: DerivExternalEvidenceIntake,
) -> tuple[DerivExtractedEvidenceClaim, ...]:
    """Extract advisory, source-bound claims without granting authority."""
    if not isinstance(intake, DerivExternalEvidenceIntake):
        raise ValueError("intake is invalid")
    paths = {field.path for field in intake.normalized_fields}
    if any(
        not set(claim.source_field_paths) <= paths
        or (
            claim.requires_complete_source
            and intake.completeness is not DerivEvidenceCompleteness.COMPLETE
        )
        for claim in intake.claim_declarations
    ):
        return ()
    return tuple(
        DerivExtractedEvidenceClaim(
            claim.claim_id,
            intake.intake_id,
            intake.provenance.raw_material_hash,
            intake.provenance.normalized_material_hash,
            intake.provenance.source_identifier,
            intake.classification,
            claim.claim_type,
            claim.semantic_id,
            claim.value,
            claim.support_state,
            intake.applicability,
            claim.source_field_paths,
        )
        for claim in intake.claim_declarations
    )


class DerivSourceVerificationState(str, Enum):
    VERIFIED_SOURCE = "VERIFIED_SOURCE"
    REJECTED_SOURCE = "REJECTED_SOURCE"
    INSUFFICIENT_SOURCE = "INSUFFICIENT_SOURCE"


@dataclass(frozen=True, slots=True)
class DerivSourceVerificationDecision:
    verification_id: str
    intake_id: str
    raw_material_hash: str
    normalized_material_hash: str
    source_identifier: str
    classification: DerivEvidenceClassification
    applicability: DerivEvidenceApplicability
    state: DerivSourceVerificationState
    verified_by: str
    verified_at: datetime

    def __post_init__(self) -> None:
        for name in ("verification_id", "intake_id", "source_identifier", "verified_by"):
            _text(name, getattr(self, name))
        _hash("raw_material_hash", self.raw_material_hash)
        _hash("normalized_material_hash", self.normalized_material_hash)
        if not isinstance(self.classification, DerivEvidenceClassification):
            raise ValueError("verification classification is invalid")
        if not isinstance(self.applicability, DerivEvidenceApplicability):
            raise ValueError("verification applicability is invalid")
        if not isinstance(self.state, DerivSourceVerificationState):
            raise ValueError("source verification state is invalid")
        _time("verified_at", self.verified_at)


class DerivEvidenceRevocationTarget(str, Enum):
    INTAKE = "INTAKE"
    SOURCE_VERIFICATION = "SOURCE_VERIFICATION"


@dataclass(frozen=True, slots=True)
class DerivEvidenceRevocation:
    revocation_id: str
    target_kind: DerivEvidenceRevocationTarget
    target_id: str
    reason: str
    revoked_at: datetime

    def __post_init__(self) -> None:
        for name in ("revocation_id", "target_id", "reason"):
            _text(name, getattr(self, name))
        if not isinstance(self.target_kind, DerivEvidenceRevocationTarget):
            raise ValueError("revocation target is invalid")
        _time("revoked_at", self.revoked_at)


class DerivEvidenceReadinessState(str, Enum):
    READY_FOR_SEMANTIC_REVIEW = "READY_FOR_SEMANTIC_REVIEW"
    INSUFFICIENT = "INSUFFICIENT"
    REJECTED = "REJECTED"
    CONFLICT = "CONFLICT"
    PRODUCTION_EVIDENCE_NOT_AVAILABLE = "PRODUCTION_EVIDENCE_NOT_AVAILABLE"


class DerivEvidenceReadinessReason(str, Enum):
    SOURCE_READY = "SOURCE_READY"
    SYNTHETIC_NOT_PRODUCTION = "SYNTHETIC_NOT_PRODUCTION"
    SOURCE_NOT_VERIFIED = "SOURCE_NOT_VERIFIED"
    MATERIAL_HASH_MISMATCH = "MATERIAL_HASH_MISMATCH"
    NORMALIZATION_HASH_MISMATCH = "NORMALIZATION_HASH_MISMATCH"
    CLAIM_BINDING_MISMATCH = "CLAIM_BINDING_MISMATCH"
    SOURCE_INCOMPLETE = "SOURCE_INCOMPLETE"
    PROVENANCE_UNKNOWN = "PROVENANCE_UNKNOWN"
    SCOPE_MISMATCH = "SCOPE_MISMATCH"
    EVIDENCE_CONFLICT = "EVIDENCE_CONFLICT"
    EVIDENCE_REVOKED = "EVIDENCE_REVOKED"
    SOURCE_VERIFICATION_REVOKED = "SOURCE_VERIFICATION_REVOKED"
    EVIDENCE_STALE = "EVIDENCE_STALE"
    NO_PRODUCTION_EVIDENCE = "NO_PRODUCTION_EVIDENCE"


@dataclass(frozen=True, slots=True)
class DerivEvidenceReadinessResult:
    state: DerivEvidenceReadinessState
    reason_codes: frozenset[DerivEvidenceReadinessReason]


def validate_deriv_evidence_for_semantic_review(
    intakes: tuple[DerivExternalEvidenceIntake, ...],
    verifications: tuple[DerivSourceVerificationDecision, ...],
    claims: tuple[DerivExtractedEvidenceClaim, ...],
    expected_applicability: DerivEvidenceApplicability,
    expected_account_scope: str | None,
    evaluation_at: datetime,
    revocations: tuple[DerivEvidenceRevocation, ...] = (),
) -> DerivEvidenceReadinessResult:
    """Validate source readiness only; never create semantic or proof authority."""
    _time("evaluation_at", evaluation_at)
    if expected_account_scope is not None:
        _text("expected_account_scope", expected_account_scope)
    if not intakes:
        return DerivEvidenceReadinessResult(
            DerivEvidenceReadinessState.PRODUCTION_EVIDENCE_NOT_AVAILABLE,
            frozenset({DerivEvidenceReadinessReason.NO_PRODUCTION_EVIDENCE}),
        )
    reasons: set[DerivEvidenceReadinessReason] = set()
    verification_by_intake = {item.intake_id: item for item in verifications}
    claims_by_intake: dict[str, list[DerivExtractedEvidenceClaim]] = {}
    for claim in claims:
        claims_by_intake.setdefault(claim.intake_id, []).append(claim)
    for intake in intakes:
        if intake.classification is not DerivEvidenceClassification.EXTERNAL_PRODUCTION_CANDIDATE:
            reasons.add(DerivEvidenceReadinessReason.SYNTHETIC_NOT_PRODUCTION)
        raw_hash = sha256_material(intake.raw_material)
        normalized_hash = sha256_material(
            canonicalize_deriv_evidence_fields(intake.normalized_fields)
        )
        if raw_hash != intake.provenance.raw_material_hash:
            reasons.add(DerivEvidenceReadinessReason.MATERIAL_HASH_MISMATCH)
        if normalized_hash != intake.provenance.normalized_material_hash:
            reasons.add(DerivEvidenceReadinessReason.NORMALIZATION_HASH_MISMATCH)
        if intake.provenance.confidence is DerivProvenanceConfidence.UNKNOWN:
            reasons.add(DerivEvidenceReadinessReason.PROVENANCE_UNKNOWN)
        if intake.completeness is not DerivEvidenceCompleteness.COMPLETE:
            reasons.add(DerivEvidenceReadinessReason.SOURCE_INCOMPLETE)
        if intake.applicability != expected_applicability:
            reasons.add(DerivEvidenceReadinessReason.SCOPE_MISMATCH)
        if (
            intake.provenance.environment != expected_applicability.environment
            or intake.provenance.account_scope != expected_account_scope
        ):
            reasons.add(DerivEvidenceReadinessReason.SCOPE_MISMATCH)
        if intake.valid_until is not None and evaluation_at > intake.valid_until:
            reasons.add(DerivEvidenceReadinessReason.EVIDENCE_STALE)
        if any(
            record.target_kind is DerivEvidenceRevocationTarget.INTAKE
            and record.target_id == intake.intake_id
            for record in revocations
        ):
            reasons.add(DerivEvidenceReadinessReason.EVIDENCE_REVOKED)
        verification = verification_by_intake.get(intake.intake_id)
        if verification is None or verification.state is not DerivSourceVerificationState.VERIFIED_SOURCE:
            reasons.add(DerivEvidenceReadinessReason.SOURCE_NOT_VERIFIED)
        else:
            if any(
                record.target_kind is DerivEvidenceRevocationTarget.SOURCE_VERIFICATION
                and record.target_id == verification.verification_id
                for record in revocations
            ):
                reasons.add(DerivEvidenceReadinessReason.SOURCE_VERIFICATION_REVOKED)
            if (
                verification.raw_material_hash != raw_hash
                or verification.normalized_material_hash != normalized_hash
                or verification.source_identifier != intake.provenance.source_identifier
                or verification.classification != intake.classification
                or verification.applicability != intake.applicability
            ):
                reasons.add(DerivEvidenceReadinessReason.MATERIAL_HASH_MISMATCH)
        extracted = claims_by_intake.get(intake.intake_id, [])
        expected_claims = extract_deriv_semantic_claims(intake)
        if tuple(extracted) != expected_claims or any(
            claim.support_state is not DerivClaimSupportState.SUPPORTED
            for claim in extracted
        ):
            reasons.add(DerivEvidenceReadinessReason.CLAIM_BINDING_MISMATCH)
    claim_values: dict[tuple[Any, ...], str] = {}
    for claim in claims:
        key = (claim.claim_type, claim.semantic_id, claim.applicability)
        previous = claim_values.setdefault(key, claim.value)
        if previous != claim.value:
            reasons.add(DerivEvidenceReadinessReason.EVIDENCE_CONFLICT)
    if not reasons:
        return DerivEvidenceReadinessResult(
            DerivEvidenceReadinessState.READY_FOR_SEMANTIC_REVIEW,
            frozenset({DerivEvidenceReadinessReason.SOURCE_READY}),
        )
    if DerivEvidenceReadinessReason.EVIDENCE_CONFLICT in reasons:
        state = DerivEvidenceReadinessState.CONFLICT
    elif reasons <= {
        DerivEvidenceReadinessReason.SOURCE_NOT_VERIFIED,
        DerivEvidenceReadinessReason.SOURCE_INCOMPLETE,
        DerivEvidenceReadinessReason.PROVENANCE_UNKNOWN,
    }:
        state = DerivEvidenceReadinessState.INSUFFICIENT
    else:
        state = DerivEvidenceReadinessState.REJECTED
    return DerivEvidenceReadinessResult(state, frozenset(reasons))
