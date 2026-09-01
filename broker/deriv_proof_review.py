"""Offline, non-authoritative assessment of Deriv evidence-review packages."""

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
    validate_deriv_evidence_review,
)


DERIV_PROOF_REVIEW_SCHEMA_VERSION = 1
_SHA256_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")


def _required_text(name: str, value: Any) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{name} must be a nonblank string")
    return value.strip()


class DerivProofReviewState(str, Enum):
    READY_FOR_AUTHORITATIVE_PROOF_REVIEW = "READY_FOR_AUTHORITATIVE_PROOF_REVIEW"
    REJECTED = "REJECTED"
    INSUFFICIENT = "INSUFFICIENT"


class DerivProofReviewReason(str, Enum):
    REVIEW_DECISION_NOT_APPROVED = "REVIEW_DECISION_NOT_APPROVED"
    REVIEW_DECISION_STALE = "REVIEW_DECISION_STALE"
    APPLICABILITY_MISMATCH = "APPLICABILITY_MISMATCH"
    EVIDENCE_IDENTITY_MISMATCH = "EVIDENCE_IDENTITY_MISMATCH"
    CLAIM_SET_MISMATCH = "CLAIM_SET_MISMATCH"
    REVIEW_SCOPE_INCOMPLETE = "REVIEW_SCOPE_INCOMPLETE"
    REVIEW_PACKAGE_CONSISTENT = "REVIEW_PACKAGE_CONSISTENT"
    REVIEW_PACKAGE_CONFLICTING = "REVIEW_PACKAGE_CONFLICTING"


@dataclass(frozen=True, slots=True)
class DerivProofReviewAssessment:
    """Advisory assessment that terminates before proof authority."""

    schema_version: int
    assessment_id: str
    review_decision_id: str
    artifact_ids: tuple[str, ...]
    artifact_content_hashes: tuple[str, ...]
    claim_ids: tuple[str, ...]
    state: DerivProofReviewState
    reason_codes: frozenset[DerivProofReviewReason]
    reviewer_id: str
    reviewed_at: datetime
    applicability: DerivEvidenceApplicability
    rationale: str | None = None

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int:
            raise ValueError("schema_version must be a strict integer")
        if self.schema_version != DERIV_PROOF_REVIEW_SCHEMA_VERSION:
            raise ValueError("unsupported proof-review schema version")
        for name in ("assessment_id", "review_decision_id", "reviewer_id"):
            _required_text(name, getattr(self, name))
        if self.rationale is not None:
            _required_text("rationale", self.rationale)
        if type(self.artifact_ids) is not tuple or any(
            type(value) is not str or not value.strip() for value in self.artifact_ids
        ):
            raise ValueError("artifact_ids must contain nonblank strings")
        if len(self.artifact_ids) != len(set(self.artifact_ids)):
            raise ValueError("duplicate artifact IDs are not allowed")
        if type(self.artifact_content_hashes) is not tuple or any(
            type(value) is not str or not _SHA256_PATTERN.fullmatch(value)
            for value in self.artifact_content_hashes
        ):
            raise ValueError("artifact hashes must use sha256:<64 lowercase hex characters>")
        if len(self.artifact_ids) != len(self.artifact_content_hashes):
            raise ValueError("artifact IDs and hashes must be positionally aligned")
        if type(self.claim_ids) is not tuple or any(
            type(value) is not str or not value.strip() for value in self.claim_ids
        ):
            raise ValueError("claim_ids must contain nonblank strings")
        if len(self.claim_ids) != len(set(self.claim_ids)):
            raise ValueError("duplicate claim IDs are not allowed")
        if not isinstance(self.state, DerivProofReviewState):
            raise ValueError("state is invalid")
        if not isinstance(self.reason_codes, frozenset) or not self.reason_codes or any(
            not isinstance(reason, DerivProofReviewReason) for reason in self.reason_codes
        ):
            raise ValueError("reason_codes must contain recognized reasons")
        if (
            type(self.reviewed_at) is not datetime
            or self.reviewed_at.tzinfo is None
            or self.reviewed_at.utcoffset() is None
        ):
            raise ValueError("reviewed_at must be a timezone-aware datetime")
        if not isinstance(self.applicability, DerivEvidenceApplicability):
            raise ValueError("applicability is invalid")
        if self.state is DerivProofReviewState.READY_FOR_AUTHORITATIVE_PROOF_REVIEW:
            if not self.artifact_ids or not self.claim_ids:
                raise ValueError("ready assessments require a nonempty evidence package")
            if self.reason_codes != frozenset(
                {DerivProofReviewReason.REVIEW_PACKAGE_CONSISTENT}
            ):
                raise ValueError("ready assessments require REVIEW_PACKAGE_CONSISTENT")
        elif DerivProofReviewReason.REVIEW_PACKAGE_CONSISTENT in self.reason_codes:
            raise ValueError("only ready assessments may declare package consistency")


@dataclass(frozen=True, slots=True)
class DerivProofReviewValidation:
    """Non-authoritative result of validating a proof-review assessment."""

    valid: bool
    observed_reasons: frozenset[DerivProofReviewReason]


def validate_deriv_proof_review_assessment(
    assessment: DerivProofReviewAssessment,
    review_decision: DerivEvidenceReviewDecision,
    evidence_registry: DerivEvidenceRegistry,
) -> DerivProofReviewValidation:
    """Validate an assessment without constructing or registering a proof."""
    if not isinstance(assessment, DerivProofReviewAssessment):
        raise ValueError("assessment is invalid")
    if not isinstance(review_decision, DerivEvidenceReviewDecision):
        raise ValueError("review_decision is invalid")
    if not isinstance(evidence_registry, DerivEvidenceRegistry):
        raise ValueError("evidence_registry is invalid")

    reasons: set[DerivProofReviewReason] = set()
    if assessment.review_decision_id != review_decision.decision_id:
        reasons.add(DerivProofReviewReason.EVIDENCE_IDENTITY_MISMATCH)
    if (
        assessment.artifact_ids != review_decision.artifact_ids
        or assessment.artifact_content_hashes
        != review_decision.artifact_content_hashes
    ):
        reasons.add(DerivProofReviewReason.EVIDENCE_IDENTITY_MISMATCH)
    if assessment.claim_ids != review_decision.claim_ids:
        reasons.add(DerivProofReviewReason.CLAIM_SET_MISMATCH)
    if assessment.applicability != review_decision.applicability:
        reasons.add(DerivProofReviewReason.APPLICABILITY_MISMATCH)

    decision_validation = validate_deriv_evidence_review(
        review_decision, evidence_registry
    )
    if not decision_validation.valid:
        reasons.add(DerivProofReviewReason.REVIEW_DECISION_STALE)
    if review_decision.state is not DerivEvidenceDecisionState.APPROVED_FOR_PROOF_REVIEW:
        reasons.add(DerivProofReviewReason.REVIEW_DECISION_NOT_APPROVED)
        if review_decision.state is DerivEvidenceDecisionState.REJECTED:
            reasons.add(DerivProofReviewReason.REVIEW_PACKAGE_CONFLICTING)
        else:
            reasons.add(DerivProofReviewReason.REVIEW_SCOPE_INCOMPLETE)

    identity_failure = bool(
        reasons
        & {
            DerivProofReviewReason.REVIEW_DECISION_STALE,
            DerivProofReviewReason.APPLICABILITY_MISMATCH,
            DerivProofReviewReason.EVIDENCE_IDENTITY_MISMATCH,
            DerivProofReviewReason.CLAIM_SET_MISMATCH,
        }
    )
    if not reasons:
        reasons.add(DerivProofReviewReason.REVIEW_PACKAGE_CONSISTENT)
    observed = frozenset(reasons)
    if identity_failure or observed != assessment.reason_codes:
        return DerivProofReviewValidation(False, observed)

    if assessment.state is DerivProofReviewState.READY_FOR_AUTHORITATIVE_PROOF_REVIEW:
        valid = observed == frozenset(
            {DerivProofReviewReason.REVIEW_PACKAGE_CONSISTENT}
        )
    elif assessment.state is DerivProofReviewState.REJECTED:
        valid = DerivProofReviewReason.REVIEW_PACKAGE_CONFLICTING in observed
    else:
        valid = DerivProofReviewReason.REVIEW_SCOPE_INCOMPLETE in observed
    return DerivProofReviewValidation(valid, observed)
