"""Pure, offline validation of non-authoritative Deriv evidence decisions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import re
from typing import Any

from broker.deriv_evidence import (
    DerivEvidenceApplicability,
    DerivEvidenceRegistry,
    DerivEvidenceReviewState,
)


DERIV_EVIDENCE_REVIEW_SCHEMA_VERSION = 1
_SHA256_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")


def _required_text(name: str, value: Any) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{name} must be a nonblank string")
    return value.strip()


class DerivEvidenceDecisionState(str, Enum):
    APPROVED_FOR_PROOF_REVIEW = "APPROVED_FOR_PROOF_REVIEW"
    REJECTED = "REJECTED"
    INSUFFICIENT = "INSUFFICIENT"


class DerivEvidenceReviewReason(str, Enum):
    MISSING_REQUIRED_CLAIM = "MISSING_REQUIRED_CLAIM"
    ARTIFACT_REJECTED = "ARTIFACT_REJECTED"
    CLAIM_REJECTED = "CLAIM_REJECTED"
    ARTIFACT_UNREVIEWED = "ARTIFACT_UNREVIEWED"
    CLAIM_UNREVIEWED = "CLAIM_UNREVIEWED"
    APPLICABILITY_MISMATCH = "APPLICABILITY_MISMATCH"
    CONTENT_IDENTITY_MISMATCH = "CONTENT_IDENTITY_MISMATCH"
    DUPLICATE_OR_CONFLICTING_CLAIM = "DUPLICATE_OR_CONFLICTING_CLAIM"
    EVIDENCE_SET_COMPLETE = "EVIDENCE_SET_COMPLETE"


@dataclass(frozen=True, slots=True)
class DerivEvidenceReviewDecision:
    """Advisory workflow decision bound to one exact offline evidence set."""

    schema_version: int
    decision_id: str
    artifact_ids: tuple[str, ...]
    artifact_content_hashes: tuple[str, ...]
    claim_ids: tuple[str, ...]
    state: DerivEvidenceDecisionState
    reason_codes: frozenset[DerivEvidenceReviewReason]
    reviewer_id: str
    reviewed_at: datetime
    applicability: DerivEvidenceApplicability
    rationale: str | None = None

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int:
            raise ValueError("schema_version must be a strict integer")
        if self.schema_version != DERIV_EVIDENCE_REVIEW_SCHEMA_VERSION:
            raise ValueError("unsupported evidence-review schema version")
        _required_text("decision_id", self.decision_id)
        _required_text("reviewer_id", self.reviewer_id)
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
        if not isinstance(self.state, DerivEvidenceDecisionState):
            raise ValueError("state is invalid")
        if not isinstance(self.reason_codes, frozenset) or not self.reason_codes or any(
            not isinstance(reason, DerivEvidenceReviewReason)
            for reason in self.reason_codes
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
        if self.state is DerivEvidenceDecisionState.APPROVED_FOR_PROOF_REVIEW:
            if not self.artifact_ids or not self.claim_ids:
                raise ValueError("approved decisions require a nonempty evidence set")
            if self.reason_codes != frozenset(
                {DerivEvidenceReviewReason.EVIDENCE_SET_COMPLETE}
            ):
                raise ValueError("approved decisions require EVIDENCE_SET_COMPLETE")
        elif DerivEvidenceReviewReason.EVIDENCE_SET_COMPLETE in self.reason_codes:
            raise ValueError("only approved decisions may declare a complete evidence set")


@dataclass(frozen=True, slots=True)
class DerivEvidenceDecisionValidation:
    """Non-authoritative result of matching a decision to current evidence."""

    valid: bool
    observed_reasons: frozenset[DerivEvidenceReviewReason]


def validate_deriv_evidence_review(
    decision: DerivEvidenceReviewDecision,
    registry: DerivEvidenceRegistry,
) -> DerivEvidenceDecisionValidation:
    """Validate workflow state without creating proof, capability, or quantity."""
    if not isinstance(decision, DerivEvidenceReviewDecision):
        raise ValueError("decision is invalid")
    if not isinstance(registry, DerivEvidenceRegistry):
        raise ValueError("registry is invalid")

    reasons: set[DerivEvidenceReviewReason] = set()
    artifacts = []
    if not decision.artifact_ids:
        reasons.add(DerivEvidenceReviewReason.MISSING_REQUIRED_CLAIM)
    for artifact_id, expected_hash in zip(
        decision.artifact_ids, decision.artifact_content_hashes, strict=True
    ):
        artifact = registry.get_by_id(artifact_id)
        if artifact is None:
            reasons.add(DerivEvidenceReviewReason.CONTENT_IDENTITY_MISMATCH)
            continue
        artifacts.append(artifact)
        if artifact.content_hash != expected_hash:
            reasons.add(DerivEvidenceReviewReason.CONTENT_IDENTITY_MISMATCH)
        if artifact.review_state is DerivEvidenceReviewState.REJECTED:
            reasons.add(DerivEvidenceReviewReason.ARTIFACT_REJECTED)
        elif artifact.review_state is not DerivEvidenceReviewState.REVIEWED:
            reasons.add(DerivEvidenceReviewReason.ARTIFACT_UNREVIEWED)

    claims_by_id = {
        claim.claim_id: claim
        for artifact in artifacts
        for claim in artifact.claims
    }
    if not decision.claim_ids:
        reasons.add(DerivEvidenceReviewReason.MISSING_REQUIRED_CLAIM)
    selected_claims = []
    for claim_id in decision.claim_ids:
        claim = claims_by_id.get(claim_id)
        if claim is None:
            reasons.add(DerivEvidenceReviewReason.MISSING_REQUIRED_CLAIM)
            continue
        selected_claims.append(claim)
        if claim.review_state is DerivEvidenceReviewState.REJECTED:
            reasons.add(DerivEvidenceReviewReason.CLAIM_REJECTED)
        elif claim.review_state is not DerivEvidenceReviewState.REVIEWED:
            reasons.add(DerivEvidenceReviewReason.CLAIM_UNREVIEWED)
        if claim.applicability != decision.applicability:
            reasons.add(DerivEvidenceReviewReason.APPLICABILITY_MISMATCH)

    claims_by_subject = {}
    for claim in selected_claims:
        identity = (claim.claim_type, claim.subject, claim.applicability)
        previous_value = claims_by_subject.setdefault(identity, claim.value)
        if previous_value != claim.value:
            reasons.add(DerivEvidenceReviewReason.DUPLICATE_OR_CONFLICTING_CLAIM)

    structural_failure = bool(
        reasons
        & {
            DerivEvidenceReviewReason.CONTENT_IDENTITY_MISMATCH,
        }
    )
    if not reasons:
        reasons.add(DerivEvidenceReviewReason.EVIDENCE_SET_COMPLETE)

    observed = frozenset(reasons)
    if structural_failure or observed != decision.reason_codes:
        return DerivEvidenceDecisionValidation(False, observed)
    if decision.state is DerivEvidenceDecisionState.APPROVED_FOR_PROOF_REVIEW:
        valid = observed == frozenset(
            {DerivEvidenceReviewReason.EVIDENCE_SET_COMPLETE}
        )
    elif decision.state is DerivEvidenceDecisionState.REJECTED:
        valid = bool(
            observed
            & {
                DerivEvidenceReviewReason.ARTIFACT_REJECTED,
                DerivEvidenceReviewReason.CLAIM_REJECTED,
                DerivEvidenceReviewReason.APPLICABILITY_MISMATCH,
                DerivEvidenceReviewReason.DUPLICATE_OR_CONFLICTING_CLAIM,
            }
        )
    else:
        valid = bool(
            observed
            & {
                DerivEvidenceReviewReason.ARTIFACT_UNREVIEWED,
                DerivEvidenceReviewReason.CLAIM_UNREVIEWED,
                DerivEvidenceReviewReason.MISSING_REQUIRED_CLAIM,
            }
        )
    return DerivEvidenceDecisionValidation(valid, observed)
