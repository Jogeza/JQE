"""Pure, isolated Deriv proof registry-admission governance.

The immutable state in this module is not the canonical capability registry.
It records admission history only and cannot construct ``DerivLossModelProof``,
authorize risk, calculate quantity, or submit an order.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import re
from typing import Any

from broker.deriv_evidence import DerivEvidenceApplicability, DerivEvidenceRegistry
from broker.deriv_evidence_review import DerivEvidenceReviewDecision
from broker.deriv_proof_registration import (
    DerivAuthoritativeProofCandidate,
    DerivGovernanceRevocationReason,
    DerivGovernanceRevocationTarget,
    DerivIndependentVerificationDecision,
    DerivProofGovernanceRevocation,
    DerivProofRegistrationEligibility,
    DerivProofRegistrationEligibilityState,
    DerivProofRegistrationReason,
    validate_deriv_proof_registration_eligibility,
)
from broker.deriv_proof_review import DerivProofReviewAssessment


DERIV_PROOF_REGISTRY_SCHEMA_VERSION = 1
_SHA256_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")
_REQUIRED_APPLICABILITY_FIELDS = (
    "contract_family",
    "symbol",
    "quantity_basis",
    "stop_loss_semantic_id",
    "multiplier_semantics_id",
    "symbol_capability_scope",
)


def _required_text(name: str, value: Any) -> None:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{name} must be a nonblank string")


def _validate_schema(value: Any) -> None:
    if type(value) is not int:
        raise ValueError("schema_version must be a strict integer")
    if value != DERIV_PROOF_REGISTRY_SCHEMA_VERSION:
        raise ValueError("unsupported proof-registry schema version")


def _validate_hash(name: str, value: Any) -> None:
    if type(value) is not str or not _SHA256_PATTERN.fullmatch(value):
        raise ValueError(f"{name} must use sha256:<64 lowercase hex characters>")


def _validate_identity_tuple(name: str, values: Any, *, required: bool = True) -> None:
    if type(values) is not tuple or any(
        type(value) is not str or not value.strip() for value in values
    ):
        raise ValueError(f"{name} must contain nonblank strings")
    if required and not values:
        raise ValueError(f"{name} must not be empty")
    if len(values) != len(set(values)):
        raise ValueError(f"duplicate {name.replace('_', ' ')} are not allowed")


def _validate_applicability(value: Any) -> None:
    if not isinstance(value, DerivEvidenceApplicability):
        raise ValueError("applicability is invalid")
    for field_name in _REQUIRED_APPLICABILITY_FIELDS:
        _required_text(f"applicability.{field_name}", getattr(value, field_name))


def _validate_timestamp(name: str, value: Any) -> None:
    if (
        type(value) is not datetime
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError(f"{name} must be a timezone-aware datetime")


@dataclass(frozen=True, slots=True)
class DerivProofAdmissionRequest:
    """Explicit request bound to one complete immutable governance lineage."""

    schema_version: int
    admission_id: str
    proof_id: str
    candidate_id: str
    candidate_material_hash: str
    verification_decision_id: str
    source_assessment_id: str
    review_decision_id: str
    artifact_ids: tuple[str, ...]
    artifact_content_hashes: tuple[str, ...]
    claim_ids: tuple[str, ...]
    applicability: DerivEvidenceApplicability
    loss_model_id: str
    loss_model_version: int
    evidence_source_id: str
    admitted_by: str
    admitted_at: datetime

    def __post_init__(self) -> None:
        _validate_schema(self.schema_version)
        for name in (
            "admission_id",
            "proof_id",
            "candidate_id",
            "verification_decision_id",
            "source_assessment_id",
            "review_decision_id",
            "loss_model_id",
            "evidence_source_id",
            "admitted_by",
        ):
            _required_text(name, getattr(self, name))
        _validate_hash("candidate_material_hash", self.candidate_material_hash)
        if type(self.loss_model_version) is not int or self.loss_model_version <= 0:
            raise ValueError("loss_model_version must be a positive strict integer")
        _validate_identity_tuple("artifact_ids", self.artifact_ids)
        if type(self.artifact_content_hashes) is not tuple:
            raise ValueError("artifact_content_hashes must be a tuple")
        for content_hash in self.artifact_content_hashes:
            _validate_hash("artifact content hash", content_hash)
        if len(self.artifact_ids) != len(self.artifact_content_hashes):
            raise ValueError("artifact IDs and hashes must be positionally aligned")
        _validate_identity_tuple("claim_ids", self.claim_ids)
        _validate_applicability(self.applicability)
        _validate_timestamp("admitted_at", self.admitted_at)


@dataclass(frozen=True, slots=True)
class DerivProofRegistryEntry:
    """Immutable historical admission record, separate from capability state."""

    schema_version: int
    admission_id: str
    proof_id: str
    candidate_id: str
    candidate_material_hash: str
    verification_decision_id: str
    source_assessment_id: str
    review_decision_id: str
    artifact_ids: tuple[str, ...]
    artifact_content_hashes: tuple[str, ...]
    claim_ids: tuple[str, ...]
    applicability: DerivEvidenceApplicability
    loss_model_id: str
    loss_model_version: int
    evidence_source_id: str
    eligibility_state: DerivProofRegistrationEligibilityState
    eligibility_reason_codes: frozenset[DerivProofRegistrationReason]
    admitted_by: str
    admitted_at: datetime

    def __post_init__(self) -> None:
        request = DerivProofAdmissionRequest(
            schema_version=self.schema_version,
            admission_id=self.admission_id,
            proof_id=self.proof_id,
            candidate_id=self.candidate_id,
            candidate_material_hash=self.candidate_material_hash,
            verification_decision_id=self.verification_decision_id,
            source_assessment_id=self.source_assessment_id,
            review_decision_id=self.review_decision_id,
            artifact_ids=self.artifact_ids,
            artifact_content_hashes=self.artifact_content_hashes,
            claim_ids=self.claim_ids,
            applicability=self.applicability,
            loss_model_id=self.loss_model_id,
            loss_model_version=self.loss_model_version,
            evidence_source_id=self.evidence_source_id,
            admitted_by=self.admitted_by,
            admitted_at=self.admitted_at,
        )
        del request
        if (
            self.eligibility_state
            is not DerivProofRegistrationEligibilityState.ELIGIBLE_FOR_REGISTRATION
            or self.eligibility_reason_codes
            != frozenset({DerivProofRegistrationReason.REGISTRATION_CHAIN_COMPLETE})
        ):
            raise ValueError("registry entry requires complete registration eligibility")

    def authority_identity(self) -> tuple[Any, ...]:
        """Return the exact immutable proof material and authority lineage."""
        return (
            self.proof_id,
            self.candidate_id,
            self.candidate_material_hash,
            self.verification_decision_id,
            self.source_assessment_id,
            self.review_decision_id,
            self.artifact_ids,
            self.artifact_content_hashes,
            self.claim_ids,
            self.applicability,
            self.loss_model_id,
            self.loss_model_version,
            self.evidence_source_id,
        )


@dataclass(frozen=True, slots=True)
class DerivProofRegistryState:
    """Isolated immutable registry history; never the canonical registry."""

    entries: tuple[DerivProofRegistryEntry, ...] = ()

    def __post_init__(self) -> None:
        if type(self.entries) is not tuple or any(
            not isinstance(entry, DerivProofRegistryEntry) for entry in self.entries
        ):
            raise ValueError("entries must be a tuple of registry entries")
        for name, identities in (
            ("proof ID", tuple(entry.proof_id for entry in self.entries)),
            ("admission ID", tuple(entry.admission_id for entry in self.entries)),
            ("candidate ID", tuple(entry.candidate_id for entry in self.entries)),
        ):
            if len(identities) != len(set(identities)):
                raise ValueError(f"duplicate {name} is not allowed")
        if self.entries != tuple(sorted(self.entries, key=lambda entry: entry.proof_id)):
            raise ValueError("registry entries must use deterministic proof-ID ordering")

    def get_historical(self, proof_id: str) -> DerivProofRegistryEntry | None:
        _required_text("proof_id", proof_id)
        return next((entry for entry in self.entries if entry.proof_id == proof_id), None)


class DerivProofAdmissionState(str, Enum):
    ADMITTED = "ADMITTED"
    ALREADY_ADMITTED = "ALREADY_ADMITTED"
    REJECTED = "REJECTED"


class DerivProofAdmissionReason(str, Enum):
    ADMISSION_ACCEPTED = "ADMISSION_ACCEPTED"
    EXACT_DUPLICATE = "EXACT_DUPLICATE"
    ELIGIBILITY_INVALID = "ELIGIBILITY_INVALID"
    ELIGIBILITY_STALE = "ELIGIBILITY_STALE"
    CANDIDATE_MISMATCH = "CANDIDATE_MISMATCH"
    MATERIAL_HASH_MISMATCH = "MATERIAL_HASH_MISMATCH"
    VERIFICATION_MISMATCH = "VERIFICATION_MISMATCH"
    ADVISORY_CHAIN_MISMATCH = "ADVISORY_CHAIN_MISMATCH"
    EVIDENCE_IDENTITY_MISMATCH = "EVIDENCE_IDENTITY_MISMATCH"
    CLAIM_SET_MISMATCH = "CLAIM_SET_MISMATCH"
    APPLICABILITY_MISMATCH = "APPLICABILITY_MISMATCH"
    LOSS_MODEL_IDENTITY_MISMATCH = "LOSS_MODEL_IDENTITY_MISMATCH"
    CANDIDATE_REVOKED = "CANDIDATE_REVOKED"
    VERIFICATION_REVOKED = "VERIFICATION_REVOKED"
    VERIFICATION_SUPERSEDED = "VERIFICATION_SUPERSEDED"
    PROOF_REVOKED = "PROOF_REVOKED"
    PROOF_ID_CONFLICT = "PROOF_ID_CONFLICT"
    REGISTRY_STATE_CONFLICT = "REGISTRY_STATE_CONFLICT"
    REVOCATION_RECORD_CONFLICT = "REVOCATION_RECORD_CONFLICT"


@dataclass(frozen=True, slots=True)
class DerivProofAdmissionResult:
    state: DerivProofAdmissionState
    reason_codes: frozenset[DerivProofAdmissionReason]
    entry: DerivProofRegistryEntry | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.state, DerivProofAdmissionState):
            raise ValueError("admission state is invalid")
        if not isinstance(self.reason_codes, frozenset) or not self.reason_codes or any(
            not isinstance(reason, DerivProofAdmissionReason)
            for reason in self.reason_codes
        ):
            raise ValueError("reason_codes must contain recognized reasons")
        expected = {
            DerivProofAdmissionState.ADMITTED: DerivProofAdmissionReason.ADMISSION_ACCEPTED,
            DerivProofAdmissionState.ALREADY_ADMITTED: (
                DerivProofAdmissionReason.EXACT_DUPLICATE
            ),
        }
        if self.state in expected:
            if self.reason_codes != frozenset({expected[self.state]}) or self.entry is None:
                raise ValueError("successful admission result is inconsistent")
        elif self.entry is not None or self.reason_codes & frozenset(expected.values()):
            raise ValueError("rejected admission result is inconsistent")


@dataclass(frozen=True, slots=True)
class DerivProofAdmissionOutcome:
    result: DerivProofAdmissionResult
    registry: DerivProofRegistryState

    def __post_init__(self) -> None:
        if not isinstance(self.result, DerivProofAdmissionResult):
            raise ValueError("result is invalid")
        if not isinstance(self.registry, DerivProofRegistryState):
            raise ValueError("registry is invalid")


def _request_authority_identity(request: DerivProofAdmissionRequest) -> tuple[Any, ...]:
    return (
        request.proof_id,
        request.candidate_id,
        request.candidate_material_hash,
        request.verification_decision_id,
        request.source_assessment_id,
        request.review_decision_id,
        request.artifact_ids,
        request.artifact_content_hashes,
        request.claim_ids,
        request.applicability,
        request.loss_model_id,
        request.loss_model_version,
        request.evidence_source_id,
    )


def _validate_revocations(
    request: DerivProofAdmissionRequest,
    verification: DerivIndependentVerificationDecision,
    revocations: tuple[DerivProofGovernanceRevocation, ...],
) -> set[DerivProofAdmissionReason]:
    reasons: set[DerivProofAdmissionReason] = set()
    revocation_ids = tuple(record.revocation_id for record in revocations)
    if len(revocation_ids) != len(set(revocation_ids)):
        reasons.add(DerivProofAdmissionReason.REVOCATION_RECORD_CONFLICT)
    for record in revocations:
        if (
            record.target_kind is DerivGovernanceRevocationTarget.CANDIDATE
            and record.target_id == request.candidate_id
        ):
            reasons.add(DerivProofAdmissionReason.CANDIDATE_REVOKED)
        elif (
            record.target_kind
            is DerivGovernanceRevocationTarget.INDEPENDENT_VERIFICATION
            and record.target_id == verification.verification_decision_id
        ):
            reasons.add(
                DerivProofAdmissionReason.VERIFICATION_SUPERSEDED
                if record.reason is DerivGovernanceRevocationReason.SUPERSEDED
                else DerivProofAdmissionReason.VERIFICATION_REVOKED
            )
        elif (
            record.target_kind is DerivGovernanceRevocationTarget.REGISTERED_PROOF
            and record.target_id == request.proof_id
        ):
            reasons.add(DerivProofAdmissionReason.PROOF_REVOKED)
    return reasons


def admit_deriv_proof_registry_entry(
    registry: DerivProofRegistryState,
    request: DerivProofAdmissionRequest,
    eligibility: DerivProofRegistrationEligibility,
    candidate: DerivAuthoritativeProofCandidate,
    verification: DerivIndependentVerificationDecision,
    source_assessment: DerivProofReviewAssessment,
    review_decision: DerivEvidenceReviewDecision,
    evidence_registry: DerivEvidenceRegistry,
    revocations: tuple[DerivProofGovernanceRevocation, ...] = (),
) -> DerivProofAdmissionOutcome:
    """Revalidate and transform isolated state without touching capability authority."""
    if not isinstance(registry, DerivProofRegistryState):
        raise ValueError("registry is invalid")
    if not isinstance(request, DerivProofAdmissionRequest):
        raise ValueError("request is invalid")
    if not isinstance(eligibility, DerivProofRegistrationEligibility):
        raise ValueError("eligibility is invalid")
    if not isinstance(candidate, DerivAuthoritativeProofCandidate):
        raise ValueError("candidate is invalid")
    if not isinstance(verification, DerivIndependentVerificationDecision):
        raise ValueError("verification is invalid")
    if type(revocations) is not tuple or any(
        not isinstance(record, DerivProofGovernanceRevocation)
        for record in revocations
    ):
        raise ValueError("revocations must be an immutable tuple")

    reasons: set[DerivProofAdmissionReason] = set()
    recomputed = validate_deriv_proof_registration_eligibility(
        candidate,
        verification,
        source_assessment,
        review_decision,
        evidence_registry,
        revocations,
    )
    if eligibility.state is not DerivProofRegistrationEligibilityState.ELIGIBLE_FOR_REGISTRATION:
        reasons.add(DerivProofAdmissionReason.ELIGIBILITY_INVALID)
    if recomputed != eligibility or not recomputed.eligible:
        reasons.add(DerivProofAdmissionReason.ELIGIBILITY_STALE)

    if request.candidate_id != candidate.candidate_id:
        reasons.add(DerivProofAdmissionReason.CANDIDATE_MISMATCH)
    if request.candidate_material_hash != candidate.candidate_material_hash:
        reasons.add(DerivProofAdmissionReason.MATERIAL_HASH_MISMATCH)
    if request.verification_decision_id != verification.verification_decision_id:
        reasons.add(DerivProofAdmissionReason.VERIFICATION_MISMATCH)
    if (
        request.source_assessment_id != source_assessment.assessment_id
        or request.review_decision_id != review_decision.decision_id
    ):
        reasons.add(DerivProofAdmissionReason.ADVISORY_CHAIN_MISMATCH)
    if (
        request.artifact_ids != candidate.artifact_ids
        or request.artifact_content_hashes != candidate.artifact_content_hashes
    ):
        reasons.add(DerivProofAdmissionReason.EVIDENCE_IDENTITY_MISMATCH)
    if request.claim_ids != candidate.claim_ids:
        reasons.add(DerivProofAdmissionReason.CLAIM_SET_MISMATCH)
    if request.applicability != candidate.applicability:
        reasons.add(DerivProofAdmissionReason.APPLICABILITY_MISMATCH)
    if (
        request.loss_model_id != candidate.loss_model_id
        or request.loss_model_version != candidate.loss_model_version
        or request.evidence_source_id != candidate.evidence_source_id
    ):
        reasons.add(DerivProofAdmissionReason.LOSS_MODEL_IDENTITY_MISMATCH)
    reasons.update(_validate_revocations(request, verification, revocations))

    existing = registry.get_historical(request.proof_id)
    if existing is not None:
        if existing.authority_identity() == _request_authority_identity(request):
            if reasons:
                return DerivProofAdmissionOutcome(
                    DerivProofAdmissionResult(
                        DerivProofAdmissionState.REJECTED, frozenset(reasons)
                    ),
                    registry,
                )
            return DerivProofAdmissionOutcome(
                DerivProofAdmissionResult(
                    DerivProofAdmissionState.ALREADY_ADMITTED,
                    frozenset({DerivProofAdmissionReason.EXACT_DUPLICATE}),
                    existing,
                ),
                registry,
            )
        reasons.add(DerivProofAdmissionReason.PROOF_ID_CONFLICT)
    if any(
        entry.admission_id == request.admission_id
        or entry.candidate_id == request.candidate_id
        for entry in registry.entries
    ):
        reasons.add(DerivProofAdmissionReason.REGISTRY_STATE_CONFLICT)
    if reasons:
        return DerivProofAdmissionOutcome(
            DerivProofAdmissionResult(
                DerivProofAdmissionState.REJECTED, frozenset(reasons)
            ),
            registry,
        )

    entry = DerivProofRegistryEntry(
        schema_version=request.schema_version,
        admission_id=request.admission_id,
        proof_id=request.proof_id,
        candidate_id=request.candidate_id,
        candidate_material_hash=request.candidate_material_hash,
        verification_decision_id=request.verification_decision_id,
        source_assessment_id=request.source_assessment_id,
        review_decision_id=request.review_decision_id,
        artifact_ids=request.artifact_ids,
        artifact_content_hashes=request.artifact_content_hashes,
        claim_ids=request.claim_ids,
        applicability=request.applicability,
        loss_model_id=request.loss_model_id,
        loss_model_version=request.loss_model_version,
        evidence_source_id=request.evidence_source_id,
        eligibility_state=eligibility.state,
        eligibility_reason_codes=eligibility.reason_codes,
        admitted_by=request.admitted_by,
        admitted_at=request.admitted_at,
    )
    new_registry = DerivProofRegistryState(
        tuple(sorted(registry.entries + (entry,), key=lambda item: item.proof_id))
    )
    return DerivProofAdmissionOutcome(
        DerivProofAdmissionResult(
            DerivProofAdmissionState.ADMITTED,
            frozenset({DerivProofAdmissionReason.ADMISSION_ACCEPTED}),
            entry,
        ),
        new_registry,
    )


class DerivProofLookupState(str, Enum):
    ACTIVE_ENTRY_FOUND = "ACTIVE_ENTRY_FOUND"
    NO_ENTRY = "NO_ENTRY"
    REVOKED_ENTRY = "REVOKED_ENTRY"
    CONFLICTING_STATE = "CONFLICTING_STATE"


class DerivProofLookupReason(str, Enum):
    EXACT_ACTIVE_ENTRY = "EXACT_ACTIVE_ENTRY"
    NO_EXACT_APPLICABILITY_ENTRY = "NO_EXACT_APPLICABILITY_ENTRY"
    ENTRY_REVOKED = "ENTRY_REVOKED"
    MULTIPLE_EXACT_ENTRIES = "MULTIPLE_EXACT_ENTRIES"
    REVOCATION_RECORD_CONFLICT = "REVOCATION_RECORD_CONFLICT"


@dataclass(frozen=True, slots=True)
class DerivProofLookupResult:
    state: DerivProofLookupState
    reason_codes: frozenset[DerivProofLookupReason]
    entry: DerivProofRegistryEntry | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.state, DerivProofLookupState):
            raise ValueError("lookup state is invalid")
        if not isinstance(self.reason_codes, frozenset) or not self.reason_codes or any(
            not isinstance(reason, DerivProofLookupReason)
            for reason in self.reason_codes
        ):
            raise ValueError("reason_codes must contain recognized reasons")
        expected = {
            DerivProofLookupState.ACTIVE_ENTRY_FOUND: frozenset(
                {DerivProofLookupReason.EXACT_ACTIVE_ENTRY}
            ),
            DerivProofLookupState.NO_ENTRY: frozenset(
                {DerivProofLookupReason.NO_EXACT_APPLICABILITY_ENTRY}
            ),
            DerivProofLookupState.REVOKED_ENTRY: frozenset(
                {DerivProofLookupReason.ENTRY_REVOKED}
            ),
        }
        if self.state in expected:
            if self.reason_codes != expected[self.state]:
                raise ValueError("lookup state and reasons are inconsistent")
            if (
                self.state is DerivProofLookupState.NO_ENTRY
                and self.entry is not None
            ) or (
                self.state is not DerivProofLookupState.NO_ENTRY
                and self.entry is None
            ):
                raise ValueError("lookup state and entry are inconsistent")
        elif self.entry is not None:
            raise ValueError("conflicting lookup cannot select an entry")


def lookup_deriv_proof_registry(
    registry: DerivProofRegistryState,
    applicability: DerivEvidenceApplicability,
    revocations: tuple[DerivProofGovernanceRevocation, ...] = (),
) -> DerivProofLookupResult:
    """Look up exact registry history without returning capability authority."""
    if not isinstance(registry, DerivProofRegistryState):
        raise ValueError("registry is invalid")
    _validate_applicability(applicability)
    if type(revocations) is not tuple or any(
        not isinstance(record, DerivProofGovernanceRevocation)
        for record in revocations
    ):
        raise ValueError("revocations must be an immutable tuple")

    revocation_ids = tuple(record.revocation_id for record in revocations)
    if len(revocation_ids) != len(set(revocation_ids)):
        return DerivProofLookupResult(
            DerivProofLookupState.CONFLICTING_STATE,
            frozenset({DerivProofLookupReason.REVOCATION_RECORD_CONFLICT}),
        )
    matches = tuple(
        entry for entry in registry.entries if entry.applicability == applicability
    )
    if not matches:
        return DerivProofLookupResult(
            DerivProofLookupState.NO_ENTRY,
            frozenset({DerivProofLookupReason.NO_EXACT_APPLICABILITY_ENTRY}),
        )
    if len(matches) > 1:
        return DerivProofLookupResult(
            DerivProofLookupState.CONFLICTING_STATE,
            frozenset({DerivProofLookupReason.MULTIPLE_EXACT_ENTRIES}),
        )
    entry = matches[0]
    revoked = any(
        (
            record.target_kind is DerivGovernanceRevocationTarget.CANDIDATE
            and record.target_id == entry.candidate_id
        )
        or (
            record.target_kind
            is DerivGovernanceRevocationTarget.INDEPENDENT_VERIFICATION
            and record.target_id == entry.verification_decision_id
        )
        or (
            record.target_kind is DerivGovernanceRevocationTarget.REGISTERED_PROOF
            and record.target_id == entry.proof_id
        )
        for record in revocations
    )
    if revoked:
        return DerivProofLookupResult(
            DerivProofLookupState.REVOKED_ENTRY,
            frozenset({DerivProofLookupReason.ENTRY_REVOKED}),
            entry,
        )
    return DerivProofLookupResult(
        DerivProofLookupState.ACTIVE_ENTRY_FOUND,
        frozenset({DerivProofLookupReason.EXACT_ACTIVE_ENTRY}),
        entry,
    )
