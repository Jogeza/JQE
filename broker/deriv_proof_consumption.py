"""Pure validation of active Deriv proof availability for an exact capability.

Proof availability is an intermediate governance fact.  It is not stop-risk
authorization and this module cannot calculate loss, quantity, or orders.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum
import re
from typing import Any

from broker.deriv_evidence import DerivEvidenceApplicability
from broker.deriv_financial_semantics import DerivFinancialSemanticsSpecification
from broker.deriv_proof_registration import (
    DerivGovernanceRevocationReason,
    DerivGovernanceRevocationTarget,
    DerivProofGovernanceRevocation,
)
from broker.deriv_proof_registry import (
    DerivProofLookupState,
    DerivProofRegistryEntry,
    DerivProofRegistryState,
    lookup_deriv_proof_registry,
)


DERIV_PROOF_CONSUMPTION_SCHEMA_VERSION = 1
_SHA256_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")
_REQUIRED_APPLICABILITY_FIELDS = (
    "contract_family",
    "symbol",
    "account_currency",
    "environment",
    "quantity_basis",
    "stop_loss_semantic_id",
    "multiplier_semantics_id",
    "symbol_capability_scope",
)


def _required_text(name: str, value: Any) -> None:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{name} must be a nonblank string")


def _validate_hash(name: str, value: Any) -> None:
    if type(value) is not str or not _SHA256_PATTERN.fullmatch(value):
        raise ValueError(f"{name} must use sha256:<64 lowercase hex characters>")


def _validate_identity_tuple(name: str, values: Any) -> None:
    if type(values) is not tuple or not values or any(
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
    if value.environment not in {"demo", "real"}:
        raise ValueError("applicability.environment must be demo or real")


def _validate_timestamp(name: str, value: Any) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be a timezone-aware datetime")


@dataclass(frozen=True, slots=True)
class DerivProofConsumptionRequest:
    """Exact capability scope and expected immutable authoritative lineage."""

    schema_version: int
    proof_id: str
    admission_id: str
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
    valid_from: datetime
    valid_until: datetime
    evaluated_at: datetime
    financial_semantics: DerivFinancialSemanticsSpecification | None = None

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int:
            raise ValueError("schema_version must be a strict integer")
        if self.schema_version != DERIV_PROOF_CONSUMPTION_SCHEMA_VERSION:
            raise ValueError("unsupported proof-consumption schema version")
        for name in (
            "proof_id",
            "admission_id",
            "candidate_id",
            "verification_decision_id",
            "source_assessment_id",
            "review_decision_id",
            "loss_model_id",
            "evidence_source_id",
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
        for name in ("valid_from", "valid_until", "evaluated_at"):
            _validate_timestamp(name, getattr(self, name))
        if self.valid_until <= self.valid_from:
            raise ValueError("valid_until must follow valid_from")
        if self.financial_semantics is not None and (
            not isinstance(self.financial_semantics, DerivFinancialSemanticsSpecification)
            or self.financial_semantics.applicability != self.applicability
        ):
            raise ValueError("financial semantics are inconsistent")


class DerivProofConsumptionState(str, Enum):
    PROOF_AVAILABLE = "PROOF_AVAILABLE"
    PROOF_UNAVAILABLE = "PROOF_UNAVAILABLE"
    PROOF_REVOKED = "PROOF_REVOKED"
    PROOF_CONFLICT = "PROOF_CONFLICT"


class DerivProofConsumptionReason(str, Enum):
    EXACT_ACTIVE_PROOF = "EXACT_ACTIVE_PROOF"
    NO_MATCHING_PROOF = "NO_MATCHING_PROOF"
    PROOF_REVOKED = "PROOF_REVOKED"
    CANDIDATE_REVOKED = "CANDIDATE_REVOKED"
    VERIFICATION_REVOKED = "VERIFICATION_REVOKED"
    VERIFICATION_SUPERSEDED = "VERIFICATION_SUPERSEDED"
    APPLICABILITY_MISMATCH = "APPLICABILITY_MISMATCH"
    MATERIAL_HASH_MISMATCH = "MATERIAL_HASH_MISMATCH"
    LINEAGE_MISMATCH = "LINEAGE_MISMATCH"
    REGISTRY_CONFLICT = "REGISTRY_CONFLICT"
    REVOCATION_CONFLICT = "REVOCATION_CONFLICT"
    MALFORMED_REGISTRY_STATE = "MALFORMED_REGISTRY_STATE"
    PROOF_NOT_YET_EFFECTIVE = "PROOF_NOT_YET_EFFECTIVE"
    PROOF_EXPIRED = "PROOF_EXPIRED"


@dataclass(frozen=True, slots=True)
class DerivProofConsumptionResult:
    """Proof-availability result with no risk or execution authority."""

    state: DerivProofConsumptionState
    reason_codes: frozenset[DerivProofConsumptionReason]
    entry: DerivProofRegistryEntry | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.state, DerivProofConsumptionState):
            raise ValueError("consumption state is invalid")
        if not isinstance(self.reason_codes, frozenset) or not self.reason_codes or any(
            not isinstance(reason, DerivProofConsumptionReason)
            for reason in self.reason_codes
        ):
            raise ValueError("reason_codes must contain recognized reasons")
        available = DerivProofConsumptionReason.EXACT_ACTIVE_PROOF
        revocations = frozenset(
            {
                DerivProofConsumptionReason.PROOF_REVOKED,
                DerivProofConsumptionReason.CANDIDATE_REVOKED,
                DerivProofConsumptionReason.VERIFICATION_REVOKED,
                DerivProofConsumptionReason.VERIFICATION_SUPERSEDED,
            }
        )
        conflicts = frozenset(
            {
                DerivProofConsumptionReason.REGISTRY_CONFLICT,
                DerivProofConsumptionReason.REVOCATION_CONFLICT,
            }
        )
        if self.state is DerivProofConsumptionState.PROOF_AVAILABLE:
            if self.reason_codes != frozenset({available}) or self.entry is None:
                raise ValueError("available result is inconsistent")
        elif self.entry is not None or available in self.reason_codes:
            raise ValueError("unavailable result cannot expose an active entry")
        elif self.state is DerivProofConsumptionState.PROOF_REVOKED:
            if not self.reason_codes & revocations:
                raise ValueError("revoked result requires a revocation reason")
        elif self.state is DerivProofConsumptionState.PROOF_CONFLICT:
            if not self.reason_codes & conflicts:
                raise ValueError("conflict result requires a conflict reason")
        elif self.reason_codes & (revocations | conflicts):
            raise ValueError("unavailable result has an inconsistent reason")

    @property
    def authoritative_loss_model_proof_available(self) -> bool:
        """Intermediate fact only; it is not stop-risk authorization."""
        return self.state is DerivProofConsumptionState.PROOF_AVAILABLE


def _registry_is_well_formed(registry: Any) -> bool:
    if not isinstance(registry, DerivProofRegistryState):
        return False
    try:
        rebuilt_entries = tuple(replace(entry) for entry in registry.entries)
        rebuilt = DerivProofRegistryState(rebuilt_entries)
    except (AttributeError, TypeError, ValueError):
        return False
    return rebuilt == registry


def _revocation_reasons(
    entry: DerivProofRegistryEntry,
    revocations: tuple[DerivProofGovernanceRevocation, ...],
) -> frozenset[DerivProofConsumptionReason]:
    reasons: set[DerivProofConsumptionReason] = set()
    for record in revocations:
        if (
            record.target_kind is DerivGovernanceRevocationTarget.REGISTERED_PROOF
            and record.target_id == entry.proof_id
        ):
            reasons.add(DerivProofConsumptionReason.PROOF_REVOKED)
        elif (
            record.target_kind is DerivGovernanceRevocationTarget.CANDIDATE
            and record.target_id == entry.candidate_id
        ):
            reasons.add(DerivProofConsumptionReason.CANDIDATE_REVOKED)
        elif (
            record.target_kind
            is DerivGovernanceRevocationTarget.INDEPENDENT_VERIFICATION
            and record.target_id == entry.verification_decision_id
        ):
            reasons.add(
                DerivProofConsumptionReason.VERIFICATION_SUPERSEDED
                if record.reason is DerivGovernanceRevocationReason.SUPERSEDED
                else DerivProofConsumptionReason.VERIFICATION_REVOKED
            )
    return frozenset(reasons)


def _revocations_conflict(
    revocations: tuple[DerivProofGovernanceRevocation, ...],
) -> bool:
    """Reject reused identities or contradictory records for one target."""
    by_id: dict[str, DerivProofGovernanceRevocation] = {}
    by_target: dict[
        tuple[DerivGovernanceRevocationTarget, str],
        DerivProofGovernanceRevocation,
    ] = {}
    for record in revocations:
        existing_id = by_id.get(record.revocation_id)
        if existing_id is not None:
            return True
        by_id[record.revocation_id] = record
        target = (record.target_kind, record.target_id)
        existing_target = by_target.get(target)
        if existing_target is not None and (
            existing_target.reason is not record.reason
            or existing_target.superseded_by_id != record.superseded_by_id
        ):
            return True
        by_target[target] = record
    return False


def validate_authoritative_proof_for_capability(
    registry: DerivProofRegistryState,
    request: DerivProofConsumptionRequest,
    revocations: tuple[DerivProofGovernanceRevocation, ...] = (),
) -> DerivProofConsumptionResult:
    """Determine exact active proof availability without authorizing stop risk."""
    if not isinstance(request, DerivProofConsumptionRequest):
        raise ValueError("request is invalid")
    if not _registry_is_well_formed(registry):
        return DerivProofConsumptionResult(
            DerivProofConsumptionState.PROOF_UNAVAILABLE,
            frozenset({DerivProofConsumptionReason.MALFORMED_REGISTRY_STATE}),
        )
    if type(revocations) is not tuple or any(
        not isinstance(record, DerivProofGovernanceRevocation)
        for record in revocations
    ):
        return DerivProofConsumptionResult(
            DerivProofConsumptionState.PROOF_CONFLICT,
            frozenset({DerivProofConsumptionReason.REVOCATION_CONFLICT}),
        )
    if _revocations_conflict(revocations):
        return DerivProofConsumptionResult(
            DerivProofConsumptionState.PROOF_CONFLICT,
            frozenset({DerivProofConsumptionReason.REVOCATION_CONFLICT}),
        )

    lookup = lookup_deriv_proof_registry(
        registry, request.applicability, revocations
    )
    if lookup.state is DerivProofLookupState.CONFLICTING_STATE:
        return DerivProofConsumptionResult(
            DerivProofConsumptionState.PROOF_CONFLICT,
            frozenset({DerivProofConsumptionReason.REGISTRY_CONFLICT}),
        )
    if lookup.state is DerivProofLookupState.NO_ENTRY:
        reason = (
            DerivProofConsumptionReason.NO_MATCHING_PROOF
            if not registry.entries
            else DerivProofConsumptionReason.APPLICABILITY_MISMATCH
        )
        return DerivProofConsumptionResult(
            DerivProofConsumptionState.PROOF_UNAVAILABLE, frozenset({reason})
        )
    if lookup.entry is None:
        return DerivProofConsumptionResult(
            DerivProofConsumptionState.PROOF_UNAVAILABLE,
            frozenset({DerivProofConsumptionReason.MALFORMED_REGISTRY_STATE}),
        )
    if lookup.state is DerivProofLookupState.REVOKED_ENTRY:
        reasons = _revocation_reasons(lookup.entry, revocations)
        return DerivProofConsumptionResult(
            DerivProofConsumptionState.PROOF_REVOKED,
            reasons or frozenset({DerivProofConsumptionReason.PROOF_REVOKED}),
        )

    entry = lookup.entry
    reasons: set[DerivProofConsumptionReason] = set()
    if (
        request.candidate_material_hash != entry.candidate_material_hash
        or request.artifact_content_hashes != entry.artifact_content_hashes
    ):
        reasons.add(DerivProofConsumptionReason.MATERIAL_HASH_MISMATCH)
    if (
        request.proof_id != entry.proof_id
        or request.admission_id != entry.admission_id
        or request.candidate_id != entry.candidate_id
        or request.verification_decision_id != entry.verification_decision_id
        or request.source_assessment_id != entry.source_assessment_id
        or request.review_decision_id != entry.review_decision_id
        or request.artifact_ids != entry.artifact_ids
        or request.claim_ids != entry.claim_ids
        or request.loss_model_id != entry.loss_model_id
        or request.loss_model_version != entry.loss_model_version
        or request.evidence_source_id != entry.evidence_source_id
        or request.valid_from != entry.valid_from
        or request.valid_until != entry.valid_until
        or request.financial_semantics != entry.financial_semantics
    ):
        reasons.add(DerivProofConsumptionReason.LINEAGE_MISMATCH)
    if request.evaluated_at < entry.valid_from:
        reasons.add(DerivProofConsumptionReason.PROOF_NOT_YET_EFFECTIVE)
    if request.evaluated_at > entry.valid_until:
        reasons.add(DerivProofConsumptionReason.PROOF_EXPIRED)
    if reasons:
        return DerivProofConsumptionResult(
            DerivProofConsumptionState.PROOF_UNAVAILABLE, frozenset(reasons)
        )
    return DerivProofConsumptionResult(
        DerivProofConsumptionState.PROOF_AVAILABLE,
        frozenset({DerivProofConsumptionReason.EXACT_ACTIVE_PROOF}),
        entry,
    )
