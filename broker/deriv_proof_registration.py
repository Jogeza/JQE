"""Pure governance checks immediately before Deriv proof registry admission.

This module models candidate material, independent verification, and revocation.
It cannot construct or register ``DerivLossModelProof`` and grants no trading
or quantity authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import re
from typing import Any

from broker.deriv_evidence import DerivEvidenceApplicability, DerivEvidenceRegistry
from broker.deriv_evidence_review import (
    DerivEvidenceDecisionState,
    DerivEvidenceReviewDecision,
)
from broker.deriv_financial_semantics import DerivFinancialSemanticsSpecification
from broker.deriv_proof_review import (
    DerivProofReviewAssessment,
    DerivProofReviewState,
    validate_deriv_proof_review_assessment,
)


DERIV_PROOF_REGISTRATION_SCHEMA_VERSION = 1
_SHA256_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")
_REQUIRED_APPLICABILITY_FIELDS = (
    "contract_family",
    "symbol",
    "quantity_basis",
    "stop_loss_semantic_id",
    "multiplier_semantics_id",
    "symbol_capability_scope",
)


def _required_text(name: str, value: Any) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{name} must be a nonblank string")
    return value.strip()


def _validate_schema_version(value: Any) -> None:
    if type(value) is not int:
        raise ValueError("schema_version must be a strict integer")
    if value != DERIV_PROOF_REGISTRATION_SCHEMA_VERSION:
        raise ValueError("unsupported proof-registration schema version")


def _validate_hash(name: str, value: Any) -> None:
    if type(value) is not str or not _SHA256_PATTERN.fullmatch(value):
        raise ValueError(f"{name} must use sha256:<64 lowercase hex characters>")


def _validate_identity_tuple(name: str, values: Any) -> None:
    if type(values) is not tuple or any(
        type(value) is not str or not value.strip() for value in values
    ):
        raise ValueError(f"{name} must contain nonblank strings")
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
class DerivAuthoritativeProofCandidate:
    """Immutable, non-authoritative identity for candidate proof material."""

    schema_version: int
    candidate_id: str
    candidate_material_hash: str
    loss_model_id: str
    loss_model_version: int
    evidence_source_id: str
    source_assessment_id: str
    review_decision_id: str
    artifact_ids: tuple[str, ...]
    artifact_content_hashes: tuple[str, ...]
    claim_ids: tuple[str, ...]
    applicability: DerivEvidenceApplicability
    financial_semantics: DerivFinancialSemanticsSpecification | None = None

    def __post_init__(self) -> None:
        _validate_schema_version(self.schema_version)
        for name in (
            "candidate_id",
            "loss_model_id",
            "evidence_source_id",
            "source_assessment_id",
            "review_decision_id",
        ):
            _required_text(name, getattr(self, name))
        _validate_hash("candidate_material_hash", self.candidate_material_hash)
        if type(self.loss_model_version) is not int or self.loss_model_version <= 0:
            raise ValueError("loss_model_version must be a positive strict integer")
        _validate_identity_tuple("artifact_ids", self.artifact_ids)
        if not self.artifact_ids:
            raise ValueError("candidate requires at least one artifact")
        if type(self.artifact_content_hashes) is not tuple:
            raise ValueError("artifact_content_hashes must be a tuple")
        for content_hash in self.artifact_content_hashes:
            _validate_hash("artifact content hash", content_hash)
        if len(self.artifact_ids) != len(self.artifact_content_hashes):
            raise ValueError("artifact IDs and hashes must be positionally aligned")
        _validate_identity_tuple("claim_ids", self.claim_ids)
        if not self.claim_ids:
            raise ValueError("candidate requires at least one claim")
        _validate_applicability(self.applicability)
        if self.financial_semantics is not None and (
            not isinstance(self.financial_semantics, DerivFinancialSemanticsSpecification)
            or self.financial_semantics.applicability != self.applicability
            or self.financial_semantics.semantic_id != self.loss_model_id
            or self.financial_semantics.semantic_version != self.loss_model_version
            or self.financial_semantics.material_hash != self.candidate_material_hash
        ):
            raise ValueError("candidate financial semantics are inconsistent")


class DerivIndependentVerificationState(str, Enum):
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    INSUFFICIENT = "INSUFFICIENT"


class DerivIndependentVerificationReason(str, Enum):
    CANDIDATE_INDEPENDENTLY_VERIFIED = "CANDIDATE_INDEPENDENTLY_VERIFIED"
    CANDIDATE_REJECTED = "CANDIDATE_REJECTED"
    VERIFICATION_SCOPE_INCOMPLETE = "VERIFICATION_SCOPE_INCOMPLETE"


@dataclass(frozen=True, slots=True)
class DerivIndependentVerificationDecision:
    """Independent decision over one exact candidate and advisory chain."""

    schema_version: int
    verification_decision_id: str
    candidate_id: str
    candidate_material_hash: str
    loss_model_id: str
    loss_model_version: int
    evidence_source_id: str
    source_assessment_id: str
    review_decision_id: str
    artifact_ids: tuple[str, ...]
    artifact_content_hashes: tuple[str, ...]
    claim_ids: tuple[str, ...]
    applicability: DerivEvidenceApplicability
    state: DerivIndependentVerificationState
    reason_codes: frozenset[DerivIndependentVerificationReason]
    verifier_id: str
    verified_at: datetime
    rationale: str | None = None
    financial_semantics: DerivFinancialSemanticsSpecification | None = None

    def __post_init__(self) -> None:
        _validate_schema_version(self.schema_version)
        for name in (
            "verification_decision_id",
            "candidate_id",
            "loss_model_id",
            "evidence_source_id",
            "source_assessment_id",
            "review_decision_id",
            "verifier_id",
        ):
            _required_text(name, getattr(self, name))
        if self.rationale is not None:
            _required_text("rationale", self.rationale)
        _validate_hash("candidate_material_hash", self.candidate_material_hash)
        if type(self.loss_model_version) is not int or self.loss_model_version <= 0:
            raise ValueError("loss_model_version must be a positive strict integer")
        _validate_identity_tuple("artifact_ids", self.artifact_ids)
        if not self.artifact_ids:
            raise ValueError("verification requires at least one artifact")
        if type(self.artifact_content_hashes) is not tuple:
            raise ValueError("artifact_content_hashes must be a tuple")
        for content_hash in self.artifact_content_hashes:
            _validate_hash("artifact content hash", content_hash)
        if len(self.artifact_ids) != len(self.artifact_content_hashes):
            raise ValueError("artifact IDs and hashes must be positionally aligned")
        _validate_identity_tuple("claim_ids", self.claim_ids)
        if not self.claim_ids:
            raise ValueError("verification requires at least one claim")
        _validate_applicability(self.applicability)
        if not isinstance(self.state, DerivIndependentVerificationState):
            raise ValueError("verification state is invalid")
        if not isinstance(self.reason_codes, frozenset) or any(
            not isinstance(reason, DerivIndependentVerificationReason)
            for reason in self.reason_codes
        ):
            raise ValueError("reason_codes must contain recognized reasons")
        expected_reasons = {
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
        if self.reason_codes != expected_reasons[self.state]:
            raise ValueError("reason_codes do not match verification state")
        _validate_timestamp("verified_at", self.verified_at)
        if self.financial_semantics is not None and (
            not isinstance(self.financial_semantics, DerivFinancialSemanticsSpecification)
            or self.financial_semantics.applicability != self.applicability
            or self.financial_semantics.semantic_id != self.loss_model_id
            or self.financial_semantics.semantic_version != self.loss_model_version
            or self.financial_semantics.material_hash != self.candidate_material_hash
        ):
            raise ValueError("verification financial semantics are inconsistent")


class DerivGovernanceRevocationTarget(str, Enum):
    CANDIDATE = "CANDIDATE"
    INDEPENDENT_VERIFICATION = "INDEPENDENT_VERIFICATION"
    REGISTERED_PROOF = "REGISTERED_PROOF"


class DerivGovernanceRevocationReason(str, Enum):
    REVOKED = "REVOKED"
    SUPERSEDED = "SUPERSEDED"
    EVIDENCE_INVALIDATED = "EVIDENCE_INVALIDATED"
    APPLICABILITY_INVALIDATED = "APPLICABILITY_INVALIDATED"


@dataclass(frozen=True, slots=True)
class DerivProofGovernanceRevocation:
    """Append-only invalidation record for candidate or proof authority."""

    schema_version: int
    revocation_id: str
    target_kind: DerivGovernanceRevocationTarget
    target_id: str
    reason: DerivGovernanceRevocationReason
    revoked_by: str
    revoked_at: datetime
    superseded_by_id: str | None = None

    def __post_init__(self) -> None:
        _validate_schema_version(self.schema_version)
        for name in ("revocation_id", "target_id", "revoked_by"):
            _required_text(name, getattr(self, name))
        if not isinstance(self.target_kind, DerivGovernanceRevocationTarget):
            raise ValueError("revocation target kind is invalid")
        if not isinstance(self.reason, DerivGovernanceRevocationReason):
            raise ValueError("revocation reason is invalid")
        _validate_timestamp("revoked_at", self.revoked_at)
        if self.reason is DerivGovernanceRevocationReason.SUPERSEDED:
            _required_text("superseded_by_id", self.superseded_by_id)
        elif self.superseded_by_id is not None:
            raise ValueError("superseded_by_id is allowed only for SUPERSEDED")


class DerivProofRegistrationEligibilityState(str, Enum):
    ELIGIBLE_FOR_REGISTRATION = "ELIGIBLE_FOR_REGISTRATION"
    INELIGIBLE = "INELIGIBLE"


class DerivProofRegistrationReason(str, Enum):
    REGISTRATION_CHAIN_COMPLETE = "REGISTRATION_CHAIN_COMPLETE"
    SOURCE_ASSESSMENT_INVALID = "SOURCE_ASSESSMENT_INVALID"
    SOURCE_ASSESSMENT_NOT_READY = "SOURCE_ASSESSMENT_NOT_READY"
    ADVISORY_DECISION_NOT_APPROVED = "ADVISORY_DECISION_NOT_APPROVED"
    CANDIDATE_IDENTITY_MISMATCH = "CANDIDATE_IDENTITY_MISMATCH"
    EVIDENCE_IDENTITY_MISMATCH = "EVIDENCE_IDENTITY_MISMATCH"
    CLAIM_SET_MISMATCH = "CLAIM_SET_MISMATCH"
    APPLICABILITY_MISMATCH = "APPLICABILITY_MISMATCH"
    INDEPENDENT_VERIFICATION_MISSING = "INDEPENDENT_VERIFICATION_MISSING"
    INDEPENDENT_VERIFICATION_NOT_VERIFIED = (
        "INDEPENDENT_VERIFICATION_NOT_VERIFIED"
    )
    INDEPENDENT_VERIFICATION_MISMATCH = "INDEPENDENT_VERIFICATION_MISMATCH"
    CANDIDATE_REVOKED = "CANDIDATE_REVOKED"
    INDEPENDENT_VERIFICATION_REVOKED = "INDEPENDENT_VERIFICATION_REVOKED"
    REVOCATION_RECORD_CONFLICT = "REVOCATION_RECORD_CONFLICT"
    FINANCIAL_SEMANTICS_MISSING = "FINANCIAL_SEMANTICS_MISSING"
    SEMANTIC_ID_MISMATCH = "SEMANTIC_ID_MISMATCH"
    SEMANTIC_VERSION_MISMATCH = "SEMANTIC_VERSION_MISMATCH"
    EQUATION_IDENTITY_MISMATCH = "EQUATION_IDENTITY_MISMATCH"
    OPERAND_SCHEMA_MISMATCH = "OPERAND_SCHEMA_MISMATCH"
    UNIT_SCHEMA_MISMATCH = "UNIT_SCHEMA_MISMATCH"
    OUTPUT_SEMANTIC_MISMATCH = "OUTPUT_SEMANTIC_MISMATCH"
    DOMAIN_MISMATCH = "DOMAIN_MISMATCH"
    ROUNDING_POLICY_MISMATCH = "ROUNDING_POLICY_MISMATCH"


@dataclass(frozen=True, slots=True)
class DerivProofRegistrationEligibility:
    """Governance-only result; it is not registry or trading authority."""

    state: DerivProofRegistrationEligibilityState
    reason_codes: frozenset[DerivProofRegistrationReason]

    def __post_init__(self) -> None:
        if not isinstance(self.state, DerivProofRegistrationEligibilityState):
            raise ValueError("eligibility state is invalid")
        if not isinstance(self.reason_codes, frozenset) or not self.reason_codes or any(
            not isinstance(reason, DerivProofRegistrationReason)
            for reason in self.reason_codes
        ):
            raise ValueError("reason_codes must contain recognized reasons")
        complete = DerivProofRegistrationReason.REGISTRATION_CHAIN_COMPLETE
        if self.state is DerivProofRegistrationEligibilityState.ELIGIBLE_FOR_REGISTRATION:
            if self.reason_codes != frozenset({complete}):
                raise ValueError("eligible result requires REGISTRATION_CHAIN_COMPLETE")
        elif complete in self.reason_codes:
            raise ValueError("ineligible result cannot declare a complete chain")

    @property
    def eligible(self) -> bool:
        return self.state is DerivProofRegistrationEligibilityState.ELIGIBLE_FOR_REGISTRATION


def _semantic_mismatch_reasons(left, right) -> set[DerivProofRegistrationReason]:
    if left == right:
        return set()
    if left is None or right is None:
        return {DerivProofRegistrationReason.FINANCIAL_SEMANTICS_MISSING}
    reasons: set[DerivProofRegistrationReason] = set()
    if left.semantic_id != right.semantic_id:
        reasons.add(DerivProofRegistrationReason.SEMANTIC_ID_MISMATCH)
    if left.semantic_version != right.semantic_version:
        reasons.add(DerivProofRegistrationReason.SEMANTIC_VERSION_MISMATCH)
    if (
        left.equation_family != right.equation_family
        or left.equation_identity_hash != right.equation_identity_hash
    ):
        reasons.add(DerivProofRegistrationReason.EQUATION_IDENTITY_MISMATCH)
    if tuple(
        (item.operand_id, item.semantic_id, item.role, item.position, item.required)
        for item in left.operands
    ) != tuple(
        (item.operand_id, item.semantic_id, item.role, item.position, item.required)
        for item in right.operands
    ):
        reasons.add(DerivProofRegistrationReason.OPERAND_SCHEMA_MISMATCH)
    if tuple(item.unit for item in left.operands) != tuple(
        item.unit for item in right.operands
    ) or left.output.unit != right.output.unit:
        reasons.add(DerivProofRegistrationReason.UNIT_SCHEMA_MISMATCH)
    if (
        left.output.semantic != right.output.semantic
        or left.output.currency_binding != right.output.currency_binding
        or left.output.explicit_currency != right.output.explicit_currency
        or left.output.signed != right.output.signed
        or left.output.zero_allowed != right.output.zero_allowed
    ):
        reasons.add(DerivProofRegistrationReason.OUTPUT_SEMANTIC_MISMATCH)
    if (
        tuple(
            (item.domain, item.lower_bound, item.upper_bound, item.zero_allowed)
            for item in left.operands
        )
        != tuple(
            (item.domain, item.lower_bound, item.upper_bound, item.zero_allowed)
            for item in right.operands
        )
        or left.domain_constraint_ids != right.domain_constraint_ids
    ):
        reasons.add(DerivProofRegistrationReason.DOMAIN_MISMATCH)
    if left.rounding != right.rounding:
        reasons.add(DerivProofRegistrationReason.ROUNDING_POLICY_MISMATCH)
    return reasons or {DerivProofRegistrationReason.CANDIDATE_IDENTITY_MISMATCH}


def validate_deriv_proof_registration_eligibility(
    candidate: DerivAuthoritativeProofCandidate,
    verification: DerivIndependentVerificationDecision | None,
    source_assessment: DerivProofReviewAssessment,
    review_decision: DerivEvidenceReviewDecision,
    evidence_registry: DerivEvidenceRegistry,
    revocations: tuple[DerivProofGovernanceRevocation, ...] = (),
) -> DerivProofRegistrationEligibility:
    """Evaluate governance prerequisites without admitting or creating a proof."""
    if not isinstance(candidate, DerivAuthoritativeProofCandidate):
        raise ValueError("candidate is invalid")
    if verification is not None and not isinstance(
        verification, DerivIndependentVerificationDecision
    ):
        raise ValueError("verification is invalid")
    if not isinstance(source_assessment, DerivProofReviewAssessment):
        raise ValueError("source_assessment is invalid")
    if not isinstance(review_decision, DerivEvidenceReviewDecision):
        raise ValueError("review_decision is invalid")
    if not isinstance(evidence_registry, DerivEvidenceRegistry):
        raise ValueError("evidence_registry is invalid")
    if type(revocations) is not tuple or any(
        not isinstance(record, DerivProofGovernanceRevocation)
        for record in revocations
    ):
        raise ValueError("revocations must be an immutable tuple of revocation records")

    reasons: set[DerivProofRegistrationReason] = set()
    assessment_validation = validate_deriv_proof_review_assessment(
        source_assessment, review_decision, evidence_registry
    )
    if not assessment_validation.valid:
        reasons.add(DerivProofRegistrationReason.SOURCE_ASSESSMENT_INVALID)
    if (
        source_assessment.state
        is not DerivProofReviewState.READY_FOR_AUTHORITATIVE_PROOF_REVIEW
    ):
        reasons.add(DerivProofRegistrationReason.SOURCE_ASSESSMENT_NOT_READY)
    if review_decision.state is not DerivEvidenceDecisionState.APPROVED_FOR_PROOF_REVIEW:
        reasons.add(DerivProofRegistrationReason.ADVISORY_DECISION_NOT_APPROVED)

    if (
        candidate.source_assessment_id != source_assessment.assessment_id
        or candidate.review_decision_id != review_decision.decision_id
    ):
        reasons.add(DerivProofRegistrationReason.CANDIDATE_IDENTITY_MISMATCH)
    if (
        candidate.artifact_ids != source_assessment.artifact_ids
        or candidate.artifact_content_hashes
        != source_assessment.artifact_content_hashes
    ):
        reasons.add(DerivProofRegistrationReason.EVIDENCE_IDENTITY_MISMATCH)
    if candidate.claim_ids != source_assessment.claim_ids:
        reasons.add(DerivProofRegistrationReason.CLAIM_SET_MISMATCH)
    if candidate.applicability != source_assessment.applicability:
        reasons.add(DerivProofRegistrationReason.APPLICABILITY_MISMATCH)
    reasons.update(
        _semantic_mismatch_reasons(
            candidate.financial_semantics, source_assessment.financial_semantics
        )
    )

    if verification is None:
        reasons.add(DerivProofRegistrationReason.INDEPENDENT_VERIFICATION_MISSING)
    else:
        if verification.state is not DerivIndependentVerificationState.VERIFIED:
            reasons.add(
                DerivProofRegistrationReason.INDEPENDENT_VERIFICATION_NOT_VERIFIED
            )
        if (
            verification.candidate_id != candidate.candidate_id
            or verification.candidate_material_hash != candidate.candidate_material_hash
            or verification.loss_model_id != candidate.loss_model_id
            or verification.loss_model_version != candidate.loss_model_version
            or verification.evidence_source_id != candidate.evidence_source_id
            or verification.source_assessment_id != candidate.source_assessment_id
            or verification.review_decision_id != candidate.review_decision_id
            or verification.artifact_ids != candidate.artifact_ids
            or verification.artifact_content_hashes
            != candidate.artifact_content_hashes
            or verification.claim_ids != candidate.claim_ids
        ):
            reasons.add(
                DerivProofRegistrationReason.INDEPENDENT_VERIFICATION_MISMATCH
            )
        if verification.applicability != candidate.applicability:
            reasons.add(DerivProofRegistrationReason.APPLICABILITY_MISMATCH)
        semantic_reasons = _semantic_mismatch_reasons(
            candidate.financial_semantics, verification.financial_semantics
        )
        if semantic_reasons:
            reasons.update(semantic_reasons)
            reasons.add(DerivProofRegistrationReason.INDEPENDENT_VERIFICATION_MISMATCH)

    revocation_ids = tuple(record.revocation_id for record in revocations)
    if len(revocation_ids) != len(set(revocation_ids)):
        reasons.add(DerivProofRegistrationReason.REVOCATION_RECORD_CONFLICT)
    if any(
        record.target_kind is DerivGovernanceRevocationTarget.CANDIDATE
        and record.target_id == candidate.candidate_id
        for record in revocations
    ):
        reasons.add(DerivProofRegistrationReason.CANDIDATE_REVOKED)
    if verification is not None and any(
        record.target_kind
        is DerivGovernanceRevocationTarget.INDEPENDENT_VERIFICATION
        and record.target_id == verification.verification_decision_id
        for record in revocations
    ):
        reasons.add(
            DerivProofRegistrationReason.INDEPENDENT_VERIFICATION_REVOKED
        )

    if reasons:
        return DerivProofRegistrationEligibility(
            DerivProofRegistrationEligibilityState.INELIGIBLE,
            frozenset(reasons),
        )
    return DerivProofRegistrationEligibility(
        DerivProofRegistrationEligibilityState.ELIGIBLE_FOR_REGISTRATION,
        frozenset({DerivProofRegistrationReason.REGISTRATION_CHAIN_COMPLETE}),
    )
