"""Pure proof-gated Deriv financial loss-model evaluation boundary.

The admitted governance metadata does not currently define an authoritative
financial equation.  This module therefore validates the complete boundary and
returns a controlled unsupported result without calculating loss or quantity.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
import re
from typing import Any

from broker.deriv_evidence import DerivEvidenceApplicability
from broker.deriv_proof_consumption import (
    DerivProofConsumptionRequest,
    DerivProofConsumptionResult,
    DerivProofConsumptionState,
    validate_authoritative_proof_for_capability,
)
from broker.deriv_proof_registration import DerivProofGovernanceRevocation
from broker.deriv_proof_registry import DerivProofRegistryState


DERIV_LOSS_EVALUATION_SCHEMA_VERSION = 1
_SHA256_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")


def _required_text(name: str, value: Any) -> None:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{name} must be a nonblank string")


@dataclass(frozen=True, slots=True)
class DerivFinancialInput:
    """One explicitly named Decimal input with an explicit financial unit."""

    semantic_id: str
    unit_id: str
    value: Decimal

    def __post_init__(self) -> None:
        _required_text("semantic_id", self.semantic_id)
        _required_text("unit_id", self.unit_id)
        if type(self.value) is not Decimal:
            raise ValueError("financial input value must be a Decimal")


@dataclass(frozen=True, slots=True)
class DerivLossEvaluationRequest:
    """Complete immutable proof state and proposed model inputs."""

    schema_version: int
    registry: DerivProofRegistryState
    proof_request: DerivProofConsumptionRequest
    proof_result: DerivProofConsumptionResult
    revocations: tuple[DerivProofGovernanceRevocation, ...]
    applicability: DerivEvidenceApplicability
    loss_model_id: str
    loss_model_version: int
    candidate_material_hash: str
    evidence_source_id: str
    financial_inputs: tuple[DerivFinancialInput, ...]

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int:
            raise ValueError("schema_version must be a strict integer")
        if self.schema_version != DERIV_LOSS_EVALUATION_SCHEMA_VERSION:
            raise ValueError("unsupported loss-evaluation schema version")
        if not isinstance(self.registry, DerivProofRegistryState):
            raise ValueError("registry is invalid")
        if not isinstance(self.proof_request, DerivProofConsumptionRequest):
            raise ValueError("proof_request is invalid")
        if not isinstance(self.proof_result, DerivProofConsumptionResult):
            raise ValueError("proof_result is invalid")
        if type(self.revocations) is not tuple or any(
            not isinstance(record, DerivProofGovernanceRevocation)
            for record in self.revocations
        ):
            raise ValueError("revocations must be an immutable tuple")
        if not isinstance(self.applicability, DerivEvidenceApplicability):
            raise ValueError("applicability is invalid")
        for name in (
            "loss_model_id",
            "evidence_source_id",
        ):
            _required_text(name, getattr(self, name))
        if (
            type(self.candidate_material_hash) is not str
            or not _SHA256_PATTERN.fullmatch(self.candidate_material_hash)
        ):
            raise ValueError("candidate_material_hash must be a lowercase SHA-256 ID")
        if type(self.loss_model_version) is not int or self.loss_model_version <= 0:
            raise ValueError("loss_model_version must be a positive strict integer")
        if type(self.financial_inputs) is not tuple or any(
            not isinstance(item, DerivFinancialInput)
            for item in self.financial_inputs
        ):
            raise ValueError("financial_inputs must be an immutable typed tuple")
        identities = tuple(item.semantic_id for item in self.financial_inputs)
        if len(identities) != len(set(identities)):
            raise ValueError("financial input semantic IDs must be unique")


class DerivLossEvaluationState(str, Enum):
    LOSS_EVALUATED = "LOSS_EVALUATED"
    LOSS_INPUT_INVALID = "LOSS_INPUT_INVALID"
    LOSS_MODEL_UNSUPPORTED = "LOSS_MODEL_UNSUPPORTED"
    PROOF_UNAVAILABLE = "PROOF_UNAVAILABLE"
    LOSS_CONFLICT = "LOSS_CONFLICT"


class DerivLossEvaluationReason(str, Enum):
    AUTHORITATIVE_LOSS_EVALUATED = "AUTHORITATIVE_LOSS_EVALUATED"
    PROOF_UNAVAILABLE = "PROOF_UNAVAILABLE"
    PROOF_LINEAGE_INVALID = "PROOF_LINEAGE_INVALID"
    APPLICABILITY_MISMATCH = "APPLICABILITY_MISMATCH"
    LOSS_MODEL_ID_MISMATCH = "LOSS_MODEL_ID_MISMATCH"
    LOSS_MODEL_VERSION_MISMATCH = "LOSS_MODEL_VERSION_MISMATCH"
    MATERIAL_HASH_MISMATCH = "MATERIAL_HASH_MISMATCH"
    EVIDENCE_SOURCE_MISMATCH = "EVIDENCE_SOURCE_MISMATCH"
    MODEL_UNSUPPORTED = "MODEL_UNSUPPORTED"
    INPUT_MISSING = "INPUT_MISSING"
    NUMERIC_DOMAIN_INVALID = "NUMERIC_DOMAIN_INVALID"


@dataclass(frozen=True, slots=True)
class DerivLossEvaluationResult:
    """Financial-model result only; it grants no risk or execution authority."""

    state: DerivLossEvaluationState
    reason_codes: frozenset[DerivLossEvaluationReason]
    monetary_loss: Decimal | None = None
    monetary_unit_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.state, DerivLossEvaluationState):
            raise ValueError("loss-evaluation state is invalid")
        if not isinstance(self.reason_codes, frozenset) or not self.reason_codes or any(
            not isinstance(reason, DerivLossEvaluationReason)
            for reason in self.reason_codes
        ):
            raise ValueError("reason_codes must contain recognized reasons")
        evaluated = DerivLossEvaluationReason.AUTHORITATIVE_LOSS_EVALUATED
        if self.state is DerivLossEvaluationState.LOSS_EVALUATED:
            if (
                self.reason_codes != frozenset({evaluated})
                or type(self.monetary_loss) is not Decimal
                or not self.monetary_loss.is_finite()
                or self.monetary_loss < 0
                or type(self.monetary_unit_id) is not str
                or not self.monetary_unit_id.strip()
            ):
                raise ValueError("evaluated loss result is inconsistent")
        elif (
            evaluated in self.reason_codes
            or self.monetary_loss is not None
            or self.monetary_unit_id is not None
        ):
            raise ValueError("non-evaluated result cannot expose monetary loss")
        expected = {
            DerivLossEvaluationState.PROOF_UNAVAILABLE: frozenset(
                {DerivLossEvaluationReason.PROOF_UNAVAILABLE}
            ),
            DerivLossEvaluationState.LOSS_MODEL_UNSUPPORTED: frozenset(
                {DerivLossEvaluationReason.MODEL_UNSUPPORTED}
            ),
        }
        if self.state in expected and self.reason_codes != expected[self.state]:
            raise ValueError("loss-evaluation state and reasons are inconsistent")
        if self.state is DerivLossEvaluationState.LOSS_INPUT_INVALID and not (
            self.reason_codes
            <= frozenset(
                {
                    DerivLossEvaluationReason.INPUT_MISSING,
                    DerivLossEvaluationReason.NUMERIC_DOMAIN_INVALID,
                }
            )
        ):
            raise ValueError("invalid-input result has inconsistent reasons")
        conflicts = frozenset(
            {
                DerivLossEvaluationReason.PROOF_LINEAGE_INVALID,
                DerivLossEvaluationReason.APPLICABILITY_MISMATCH,
                DerivLossEvaluationReason.LOSS_MODEL_ID_MISMATCH,
                DerivLossEvaluationReason.LOSS_MODEL_VERSION_MISMATCH,
                DerivLossEvaluationReason.MATERIAL_HASH_MISMATCH,
                DerivLossEvaluationReason.EVIDENCE_SOURCE_MISMATCH,
            }
        )
        if (
            self.state is DerivLossEvaluationState.LOSS_CONFLICT
            and not self.reason_codes <= conflicts
        ):
            raise ValueError("conflict result has inconsistent reasons")

    @property
    def authoritative_loss_model_evaluated(self) -> bool:
        return self.state is DerivLossEvaluationState.LOSS_EVALUATED


def evaluate_authoritative_deriv_loss_model(
    request: DerivLossEvaluationRequest,
) -> DerivLossEvaluationResult:
    """Revalidate proof authority and fail closed until an equation is proven."""
    if not isinstance(request, DerivLossEvaluationRequest):
        raise ValueError("request is invalid")

    recomputed = validate_authoritative_proof_for_capability(
        request.registry,
        request.proof_request,
        request.revocations,
    )
    if recomputed.state is not DerivProofConsumptionState.PROOF_AVAILABLE:
        return DerivLossEvaluationResult(
            DerivLossEvaluationState.PROOF_UNAVAILABLE,
            frozenset({DerivLossEvaluationReason.PROOF_UNAVAILABLE}),
        )
    if request.proof_result != recomputed or recomputed.entry is None:
        return DerivLossEvaluationResult(
            DerivLossEvaluationState.LOSS_CONFLICT,
            frozenset({DerivLossEvaluationReason.PROOF_LINEAGE_INVALID}),
        )

    entry = recomputed.entry
    identity_reasons: set[DerivLossEvaluationReason] = set()
    if (
        request.applicability != request.proof_request.applicability
        or request.applicability != entry.applicability
    ):
        identity_reasons.add(DerivLossEvaluationReason.APPLICABILITY_MISMATCH)
    if request.loss_model_id != entry.loss_model_id:
        identity_reasons.add(DerivLossEvaluationReason.LOSS_MODEL_ID_MISMATCH)
    if request.loss_model_version != entry.loss_model_version:
        identity_reasons.add(DerivLossEvaluationReason.LOSS_MODEL_VERSION_MISMATCH)
    if request.candidate_material_hash != entry.candidate_material_hash:
        identity_reasons.add(DerivLossEvaluationReason.MATERIAL_HASH_MISMATCH)
    if request.evidence_source_id != entry.evidence_source_id:
        identity_reasons.add(DerivLossEvaluationReason.EVIDENCE_SOURCE_MISMATCH)
    if identity_reasons:
        return DerivLossEvaluationResult(
            DerivLossEvaluationState.LOSS_CONFLICT,
            frozenset(identity_reasons),
        )

    if not request.financial_inputs:
        return DerivLossEvaluationResult(
            DerivLossEvaluationState.LOSS_INPUT_INVALID,
            frozenset({DerivLossEvaluationReason.INPUT_MISSING}),
        )
    if any(
        not item.value.is_finite() or item.value <= 0
        for item in request.financial_inputs
    ):
        return DerivLossEvaluationResult(
            DerivLossEvaluationState.LOSS_INPUT_INVALID,
            frozenset({DerivLossEvaluationReason.NUMERIC_DOMAIN_INVALID}),
        )

    # No admitted Deriv metadata currently defines operands, an equation,
    # financial output units, numeric domain, or rounding.  Never infer these.
    return DerivLossEvaluationResult(
        DerivLossEvaluationState.LOSS_MODEL_UNSUPPORTED,
        frozenset({DerivLossEvaluationReason.MODEL_UNSUPPORTED}),
    )
