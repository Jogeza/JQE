"""Offline restart-to-terms boundary with no broker or execution authority."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
import sqlite3
from typing import Any

from broker.deriv_evidence import DerivEvidenceApplicability
from broker.deriv_execution_terms import (
    DerivExecutionTerms,
    DerivExecutionTermsEvaluationState,
    DerivSyntheticFinancialPropositions,
    evaluate_synthetic_deriv_execution_terms,
)
from broker.deriv_proof_consumption import (
    DerivProofConsumptionRequest,
    DerivProofConsumptionState,
    validate_authoritative_proof_for_capability,
)
from broker.deriv_proof_registry import (
    DerivProofLookupState,
    lookup_deriv_proof_registry,
)
from broker.deriv_proof_store import DerivProofStoreError, SQLiteDerivProofStore


def _text(name: str, value: Any) -> None:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{name} must be a nonblank string")


@dataclass(frozen=True, slots=True)
class DerivExecutionTermsServiceRequest:
    """Exact offline terms request; contains no Deriv transport fields."""

    applicability: DerivEvidenceApplicability
    evaluated_at: datetime
    authorized_risk_amount: Decimal
    propositions: DerivSyntheticFinancialPropositions | None
    account_scope: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.applicability, DerivEvidenceApplicability):
            raise ValueError("applicability is invalid")
        for name in (
            "contract_family",
            "symbol",
            "account_currency",
            "environment",
            "quantity_basis",
            "stop_loss_semantic_id",
            "multiplier_semantics_id",
            "symbol_capability_scope",
        ):
            _text(f"applicability.{name}", getattr(self.applicability, name))
        if self.applicability.environment not in {"demo", "real"}:
            raise ValueError("applicability.environment must be demo or real")
        if (
            type(self.evaluated_at) is not datetime
            or self.evaluated_at.tzinfo is None
            or self.evaluated_at.utcoffset() is None
        ):
            raise ValueError("evaluated_at must be a timezone-aware datetime")
        if (
            type(self.authorized_risk_amount) is not Decimal
            or not self.authorized_risk_amount.is_finite()
            or self.authorized_risk_amount <= 0
        ):
            raise ValueError("authorized_risk_amount must be a positive finite Decimal")
        if self.propositions is not None and not isinstance(
            self.propositions, DerivSyntheticFinancialPropositions
        ):
            raise ValueError("propositions are invalid")
        if self.account_scope is not None:
            _text("account_scope", self.account_scope)


class DerivExecutionTermsServiceState(str, Enum):
    TERMS_AVAILABLE = "TERMS_AVAILABLE"
    PROOF_UNAVAILABLE = "PROOF_UNAVAILABLE"
    PROOF_REVOKED = "PROOF_REVOKED"
    PROOF_CONFLICT = "PROOF_CONFLICT"
    PROOF_STORE_UNAVAILABLE = "PROOF_STORE_UNAVAILABLE"
    MODEL_UNSUPPORTED = "MODEL_UNSUPPORTED"
    FINANCIAL_INPUT_INVALID = "FINANCIAL_INPUT_INVALID"
    RISK_BOUND_EXCEEDED = "RISK_BOUND_EXCEEDED"


@dataclass(frozen=True, slots=True)
class DerivExecutionTermsServiceResult:
    state: DerivExecutionTermsServiceState
    reason: str
    terms: DerivExecutionTerms | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.state, DerivExecutionTermsServiceState):
            raise ValueError("service result state is invalid")
        _text("reason", self.reason)
        if self.state is DerivExecutionTermsServiceState.TERMS_AVAILABLE:
            if not isinstance(self.terms, DerivExecutionTerms):
                raise ValueError("available service result requires typed terms")
        elif self.terms is not None:
            raise ValueError("unavailable service result cannot expose terms")


class OfflineDerivExecutionTermsService:
    """Reload and revalidate durable proof authority for each explicit request."""

    def __init__(self, store: SQLiteDerivProofStore) -> None:
        if not isinstance(store, SQLiteDerivProofStore):
            raise ValueError("store is invalid")
        self._store = store

    def evaluate(
        self, request: DerivExecutionTermsServiceRequest
    ) -> DerivExecutionTermsServiceResult:
        if not isinstance(request, DerivExecutionTermsServiceRequest):
            raise ValueError("request is invalid")
        try:
            durable = self._store.load()
        except (DerivProofStoreError, sqlite3.DatabaseError, OSError) as exc:
            return DerivExecutionTermsServiceResult(
                DerivExecutionTermsServiceState.PROOF_STORE_UNAVAILABLE,
                f"Durable proof store unavailable: {type(exc).__name__}",
            )

        lookup = lookup_deriv_proof_registry(
            durable.registry, request.applicability, durable.revocations
        )
        if lookup.state is DerivProofLookupState.NO_ENTRY:
            return DerivExecutionTermsServiceResult(
                DerivExecutionTermsServiceState.PROOF_UNAVAILABLE,
                "No exact proof applicability is available",
            )
        if lookup.state is DerivProofLookupState.CONFLICTING_STATE:
            return DerivExecutionTermsServiceResult(
                DerivExecutionTermsServiceState.PROOF_CONFLICT,
                "Durable proof authority is conflicting",
            )
        if lookup.entry is None:
            return DerivExecutionTermsServiceResult(
                DerivExecutionTermsServiceState.PROOF_UNAVAILABLE,
                "Exact proof entry is unavailable",
            )

        entry = lookup.entry
        proof_request = DerivProofConsumptionRequest(
            schema_version=entry.schema_version,
            proof_id=entry.proof_id,
            admission_id=entry.admission_id,
            candidate_id=entry.candidate_id,
            candidate_material_hash=entry.candidate_material_hash,
            verification_decision_id=entry.verification_decision_id,
            source_assessment_id=entry.source_assessment_id,
            review_decision_id=entry.review_decision_id,
            artifact_ids=entry.artifact_ids,
            artifact_content_hashes=entry.artifact_content_hashes,
            claim_ids=entry.claim_ids,
            applicability=request.applicability,
            loss_model_id=entry.loss_model_id,
            loss_model_version=entry.loss_model_version,
            evidence_source_id=entry.evidence_source_id,
            valid_from=entry.valid_from,
            valid_until=entry.valid_until,
            evaluated_at=request.evaluated_at,
            financial_semantics=entry.financial_semantics,
        )
        proof = validate_authoritative_proof_for_capability(
            durable.registry, proof_request, durable.revocations
        )
        if proof.state is DerivProofConsumptionState.PROOF_REVOKED:
            return DerivExecutionTermsServiceResult(
                DerivExecutionTermsServiceState.PROOF_REVOKED,
                "Exact proof authority is revoked",
            )
        if proof.state is DerivProofConsumptionState.PROOF_CONFLICT:
            return DerivExecutionTermsServiceResult(
                DerivExecutionTermsServiceState.PROOF_CONFLICT,
                "Exact proof authority is conflicting",
            )
        if proof.state is not DerivProofConsumptionState.PROOF_AVAILABLE:
            return DerivExecutionTermsServiceResult(
                DerivExecutionTermsServiceState.PROOF_UNAVAILABLE,
                "Exact proof authority is unavailable or outside its validity window",
            )
        if entry.financial_semantics is None:
            return DerivExecutionTermsServiceResult(
                DerivExecutionTermsServiceState.MODEL_UNSUPPORTED,
                "Consumed proof has no approved financial semantics",
            )

        evaluated = evaluate_synthetic_deriv_execution_terms(
            proof=proof,
            semantics=entry.financial_semantics,
            propositions=request.propositions,
            authorized_risk_amount=request.authorized_risk_amount,
            account_scope=request.account_scope,
        )
        states = {
            DerivExecutionTermsEvaluationState.VALIDATED_EXECUTION_TERMS:
                DerivExecutionTermsServiceState.TERMS_AVAILABLE,
            DerivExecutionTermsEvaluationState.PROOF_VALID_BUT_MODEL_UNSUPPORTED:
                DerivExecutionTermsServiceState.MODEL_UNSUPPORTED,
            DerivExecutionTermsEvaluationState.PROOF_UNAVAILABLE:
                DerivExecutionTermsServiceState.PROOF_UNAVAILABLE,
            DerivExecutionTermsEvaluationState.FINANCIAL_INPUT_INVALID:
                DerivExecutionTermsServiceState.FINANCIAL_INPUT_INVALID,
            DerivExecutionTermsEvaluationState.RISK_LIMIT_EXCEEDED:
                DerivExecutionTermsServiceState.RISK_BOUND_EXCEEDED,
        }
        return DerivExecutionTermsServiceResult(
            states[evaluated.state], evaluated.reason, evaluated.terms
        )
