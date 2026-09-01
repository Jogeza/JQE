"""Offline provenance records for independently reviewed Deriv source material.

Evidence recorded here is descriptive only.  It cannot create a
``DerivLossModelProof`` or authorize an execution quantity.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
import re
from typing import Any


DERIV_EVIDENCE_SCHEMA_VERSION = 1
_SHA256_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")


def _required_text(name: str, value: Any) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{name} must be a nonblank string")
    return value.strip()


def _optional_text(name: str, value: Any) -> None:
    if value is not None:
        _required_text(name, value)


class DerivEvidenceReviewState(str, Enum):
    UNREVIEWED = "UNREVIEWED"
    REVIEWED = "REVIEWED"
    REJECTED = "REJECTED"


class DerivEvidenceClaimType(str, Enum):
    CONTRACT_FAMILY_AVAILABILITY = "CONTRACT_FAMILY_AVAILABILITY"
    QUANTITY_BASIS_SEMANTICS = "QUANTITY_BASIS_SEMANTICS"
    STOP_LOSS_SEMANTICS = "STOP_LOSS_SEMANTICS"
    MULTIPLIER_SEMANTICS = "MULTIPLIER_SEMANTICS"
    SYMBOL_ELIGIBILITY = "SYMBOL_ELIGIBILITY"
    DURATION_REQUIREMENTS = "DURATION_REQUIREMENTS"
    CURRENCY_SEMANTICS = "CURRENCY_SEMANTICS"
    MINIMUM_STAKE = "MINIMUM_STAKE"
    STAKE_INCREMENT_PRECISION = "STAKE_INCREMENT_PRECISION"
    LOSS_MODEL_DESCRIPTION_IDENTITY = "LOSS_MODEL_DESCRIPTION_IDENTITY"


@dataclass(frozen=True, slots=True)
class DerivEvidenceApplicability:
    """Scope asserted by a source without asserting that the claim is true."""

    broker: str
    contract_family: str | None = None
    symbol: str | None = None
    account_currency: str | None = None
    environment: str | None = None
    quantity_basis: str | None = None
    stop_loss_semantic_id: str | None = None
    multiplier_semantics_id: str | None = None
    symbol_capability_scope: str | None = None

    def __post_init__(self) -> None:
        if _required_text("broker", self.broker).lower() != "deriv":
            raise ValueError("broker must identify Deriv")
        for name in (
            "contract_family", "symbol", "account_currency", "environment",
            "quantity_basis", "stop_loss_semantic_id", "multiplier_semantics_id",
            "symbol_capability_scope",
        ):
            _optional_text(name, getattr(self, name))


@dataclass(frozen=True, slots=True)
class DerivEvidenceClaim:
    """A recorded source assertion, not an authoritative financial proof."""

    claim_id: str
    artifact_id: str
    claim_type: DerivEvidenceClaimType
    subject: str
    value: str
    applicability: DerivEvidenceApplicability
    review_state: DerivEvidenceReviewState = DerivEvidenceReviewState.UNREVIEWED

    def __post_init__(self) -> None:
        for name in ("claim_id", "artifact_id", "subject", "value"):
            _required_text(name, getattr(self, name))
        if not isinstance(self.claim_type, DerivEvidenceClaimType):
            raise ValueError("claim_type is invalid")
        if not isinstance(self.applicability, DerivEvidenceApplicability):
            raise ValueError("applicability is invalid")
        if not isinstance(self.review_state, DerivEvidenceReviewState):
            raise ValueError("review_state is invalid")


@dataclass(frozen=True, slots=True)
class DerivEvidenceArtifact:
    """Versioned, content-addressed metadata for offline source material."""

    schema_version: int
    artifact_id: str
    source_identifier: str
    source_title: str
    source_publisher: str
    recorded_date: date
    content_hash: str
    claims: tuple[DerivEvidenceClaim, ...]
    review_state: DerivEvidenceReviewState = DerivEvidenceReviewState.UNREVIEWED
    source_version: str | None = None

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int:
            raise ValueError("schema_version must be a strict integer")
        if self.schema_version != DERIV_EVIDENCE_SCHEMA_VERSION:
            raise ValueError("unsupported evidence schema version")
        for name in (
            "artifact_id", "source_identifier", "source_title", "source_publisher",
        ):
            _required_text(name, getattr(self, name))
        _optional_text("source_version", self.source_version)
        if type(self.recorded_date) is not date or isinstance(self.recorded_date, datetime):
            raise ValueError("recorded_date must be a date")
        if type(self.content_hash) is not str or not _SHA256_PATTERN.fullmatch(
            self.content_hash
        ):
            raise ValueError("content_hash must use sha256:<64 lowercase hex characters>")
        if type(self.claims) is not tuple or any(
            not isinstance(claim, DerivEvidenceClaim) for claim in self.claims
        ):
            raise ValueError("claims must be a tuple of DerivEvidenceClaim values")
        claim_ids = tuple(claim.claim_id for claim in self.claims)
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("duplicate claim IDs are not allowed")
        if any(claim.artifact_id != self.artifact_id for claim in self.claims):
            raise ValueError("claim artifact identity mismatch")
        if not isinstance(self.review_state, DerivEvidenceReviewState):
            raise ValueError("review_state is invalid")


@dataclass(frozen=True, slots=True)
class DerivEvidenceRegistry:
    """Immutable offline catalog with no proof or capability authority."""

    artifacts: tuple[DerivEvidenceArtifact, ...] = ()

    def __post_init__(self) -> None:
        if type(self.artifacts) is not tuple or any(
            not isinstance(artifact, DerivEvidenceArtifact)
            for artifact in self.artifacts
        ):
            raise ValueError("artifacts must be a tuple of DerivEvidenceArtifact values")
        artifact_ids = tuple(artifact.artifact_id for artifact in self.artifacts)
        content_hashes = tuple(artifact.content_hash for artifact in self.artifacts)
        if len(artifact_ids) != len(set(artifact_ids)):
            raise ValueError("duplicate artifact IDs are not allowed")
        if len(content_hashes) != len(set(content_hashes)):
            raise ValueError("duplicate artifact content hashes are not allowed")

    def register(self, artifact: DerivEvidenceArtifact) -> "DerivEvidenceRegistry":
        if not isinstance(artifact, DerivEvidenceArtifact):
            raise ValueError("artifact is invalid")
        if any(existing.artifact_id == artifact.artifact_id for existing in self.artifacts):
            raise ValueError("duplicate artifact ID")
        if any(existing.content_hash == artifact.content_hash for existing in self.artifacts):
            raise ValueError("duplicate artifact content hash")
        return DerivEvidenceRegistry(self.artifacts + (artifact,))

    def get_by_id(self, artifact_id: str) -> DerivEvidenceArtifact | None:
        normalized = _required_text("artifact_id", artifact_id)
        return next(
            (artifact for artifact in self.artifacts if artifact.artifact_id == normalized),
            None,
        )

    def get_by_hash(self, content_hash: str) -> DerivEvidenceArtifact | None:
        if type(content_hash) is not str or not _SHA256_PATTERN.fullmatch(content_hash):
            raise ValueError("content_hash must use sha256:<64 lowercase hex characters>")
        return next(
            (artifact for artifact in self.artifacts if artifact.content_hash == content_hash),
            None,
        )

    def remove(self, artifact_id: str) -> "DerivEvidenceRegistry":
        normalized = _required_text("artifact_id", artifact_id)
        return DerivEvidenceRegistry(
            tuple(
                artifact for artifact in self.artifacts
                if artifact.artifact_id != normalized
            )
        )
