"""Offline, proof-bound Deriv financial terms with no execution authority."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
import re
from typing import Any

from broker.deriv_evidence import DerivEvidenceApplicability
from broker.deriv_evidence_intake import DerivEvidenceClassification
from broker.deriv_financial_semantics import (
    DerivCurrencyBinding,
    DerivFinancialSemanticsSpecification,
    DerivFinancialUnit,
    DerivOutputSemantic,
)
from broker.deriv_proof_consumption import (
    DerivProofConsumptionResult,
    DerivProofConsumptionState,
)
from broker.types import ExecutionQuantityUnit


_SHA256_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")


def _text(name: str, value: Any) -> None:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{name} must be a nonblank string")


def _decimal(name: str, value: Any, *, positive: bool) -> None:
    if type(value) is not Decimal or not value.is_finite():
        raise ValueError(f"{name} must be a finite Decimal")
    if (positive and value <= 0) or (not positive and value < 0):
        qualifier = "positive" if positive else "nonnegative"
        raise ValueError(f"{name} must be {qualifier}")


@dataclass(frozen=True, slots=True)
class DerivExecutionTerms:
    """Validated financial terms, never an instruction or execution authorization."""

    environment: str
    account_scope: str | None
    account_currency: str
    underlying_symbol: str
    contract_type: str
    stake: Decimal
    stake_unit: ExecutionQuantityUnit
    multiplier: Decimal
    stop_loss_amount: Decimal
    take_profit_amount: Decimal
    maximum_loss: Decimal
    proof_id: str
    material_hash: str
    loss_model_id: str
    loss_model_version: int
    applicability: DerivEvidenceApplicability

    def __post_init__(self) -> None:
        for name in (
            "environment",
            "account_currency",
            "underlying_symbol",
            "contract_type",
            "proof_id",
            "loss_model_id",
        ):
            _text(name, getattr(self, name))
        if self.environment not in {"demo", "real"}:
            raise ValueError("environment must be demo or real")
        if self.account_scope is not None:
            _text("account_scope", self.account_scope)
        if self.contract_type not in {"MULTUP", "MULTDOWN"}:
            raise ValueError("contract_type must be MULTUP or MULTDOWN")
        for name, positive in (
            ("stake", True),
            ("multiplier", True),
            ("stop_loss_amount", False),
            ("take_profit_amount", False),
            ("maximum_loss", False),
        ):
            _decimal(name, getattr(self, name), positive=positive)
        if self.stake_unit is not ExecutionQuantityUnit.DERIV_STAKE:
            raise ValueError("stake_unit must be DERIV_STAKE")
        if type(self.material_hash) is not str or not _SHA256_PATTERN.fullmatch(
            self.material_hash
        ):
            raise ValueError("material_hash must be a lowercase SHA-256 ID")
        if type(self.loss_model_version) is not int or self.loss_model_version <= 0:
            raise ValueError("loss_model_version must be a positive strict integer")
        if not isinstance(self.applicability, DerivEvidenceApplicability):
            raise ValueError("applicability is invalid")
        if (
            self.applicability.environment != self.environment
            or self.applicability.account_currency != self.account_currency
            or self.applicability.symbol != self.underlying_symbol
            or self.applicability.contract_family != self.contract_type
        ):
            raise ValueError("execution terms conflict with proof applicability")


@dataclass(frozen=True, slots=True)
class DerivSyntheticFinancialPropositions:
    """Explicitly synthetic established values for offline model-boundary tests."""

    classification: DerivEvidenceClassification
    stake: Decimal
    multiplier: Decimal
    stop_loss_amount: Decimal
    take_profit_amount: Decimal
    maximum_loss: Decimal | None

    def __post_init__(self) -> None:
        if self.classification is not DerivEvidenceClassification.SYNTHETIC_TEST_ONLY:
            raise ValueError("financial propositions must be explicitly synthetic")
        for name, positive in (
            ("stake", True),
            ("multiplier", True),
            ("stop_loss_amount", False),
            ("take_profit_amount", False),
        ):
            _decimal(name, getattr(self, name), positive=positive)
        if self.maximum_loss is not None:
            _decimal("maximum_loss", self.maximum_loss, positive=False)


class DerivExecutionTermsEvaluationState(str, Enum):
    VALIDATED_EXECUTION_TERMS = "VALIDATED_EXECUTION_TERMS"
    PROOF_VALID_BUT_MODEL_UNSUPPORTED = "PROOF_VALID_BUT_MODEL_UNSUPPORTED"
    PROOF_UNAVAILABLE = "PROOF_UNAVAILABLE"
    FINANCIAL_INPUT_INVALID = "FINANCIAL_INPUT_INVALID"
    RISK_LIMIT_EXCEEDED = "RISK_LIMIT_EXCEEDED"


@dataclass(frozen=True, slots=True)
class DerivExecutionTermsEvaluationResult:
    state: DerivExecutionTermsEvaluationState
    reason: str
    terms: DerivExecutionTerms | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.state, DerivExecutionTermsEvaluationState):
            raise ValueError("evaluation state is invalid")
        _text("reason", self.reason)
        if self.state is DerivExecutionTermsEvaluationState.VALIDATED_EXECUTION_TERMS:
            if not isinstance(self.terms, DerivExecutionTerms):
                raise ValueError("validated result requires execution terms")
        elif self.terms is not None:
            raise ValueError("failed result cannot expose execution terms")


def evaluate_synthetic_deriv_execution_terms(
    *,
    proof: DerivProofConsumptionResult,
    semantics: DerivFinancialSemanticsSpecification,
    propositions: DerivSyntheticFinancialPropositions | None,
    authorized_risk_amount: Decimal,
    account_scope: str | None = None,
) -> DerivExecutionTermsEvaluationResult:
    """Validate synthetic propositions without implementing a Deriv equation."""
    _decimal("authorized_risk_amount", authorized_risk_amount, positive=False)
    if proof.state is not DerivProofConsumptionState.PROOF_AVAILABLE or proof.entry is None:
        return DerivExecutionTermsEvaluationResult(
            DerivExecutionTermsEvaluationState.PROOF_UNAVAILABLE,
            "An exact active proof is required",
        )
    entry = proof.entry
    if entry.financial_semantics != semantics or semantics.material_hash != entry.candidate_material_hash:
        return DerivExecutionTermsEvaluationResult(
            DerivExecutionTermsEvaluationState.PROOF_UNAVAILABLE,
            "Financial semantics do not match consumed proof lineage",
        )
    if propositions is None:
        return DerivExecutionTermsEvaluationResult(
            DerivExecutionTermsEvaluationState.PROOF_VALID_BUT_MODEL_UNSUPPORTED,
            "No authoritative financial propositions are available",
        )
    if (
        semantics.output.semantic
        is not DerivOutputSemantic.SYNTHETIC_MONETARY_LOSS_FOR_SUPPLIED_INPUTS
        or semantics.output.unit is not DerivFinancialUnit.ACCOUNT_CURRENCY_AMOUNT
        or semantics.output.currency_binding
        is not DerivCurrencyBinding.APPLICABILITY_ACCOUNT_CURRENCY
        or semantics.take_profit_output is None
        or semantics.maximum_loss_output is None
        or semantics.take_profit_output.semantic
        is not DerivOutputSemantic.SYNTHETIC_MONETARY_PROFIT_FOR_SUPPLIED_INPUTS
        or semantics.take_profit_output.unit
        is not DerivFinancialUnit.ACCOUNT_CURRENCY_AMOUNT
        or semantics.take_profit_output.currency_binding
        is not DerivCurrencyBinding.APPLICABILITY_ACCOUNT_CURRENCY
        or semantics.maximum_loss_output.semantic
        is not DerivOutputSemantic.SYNTHETIC_MAXIMUM_MONETARY_LOSS
        or semantics.maximum_loss_output.unit
        is not DerivFinancialUnit.ACCOUNT_CURRENCY_AMOUNT
        or semantics.maximum_loss_output.currency_binding
        is not DerivCurrencyBinding.APPLICABILITY_ACCOUNT_CURRENCY
        or not semantics.take_profit_semantic_id
        or not semantics.maximum_loss_semantic_id
        or not semantics.allowed_multiplier_values
        or propositions.multiplier not in semantics.allowed_multiplier_values
    ):
        return DerivExecutionTermsEvaluationResult(
            DerivExecutionTermsEvaluationState.PROOF_VALID_BUT_MODEL_UNSUPPORTED,
            "Proof does not establish take-profit and multiplier authority",
        )
    if propositions.maximum_loss is None:
        return DerivExecutionTermsEvaluationResult(
            DerivExecutionTermsEvaluationState.FINANCIAL_INPUT_INVALID,
            "Maximum loss is unavailable",
        )
    if propositions.maximum_loss > authorized_risk_amount:
        return DerivExecutionTermsEvaluationResult(
            DerivExecutionTermsEvaluationState.RISK_LIMIT_EXCEEDED,
            "Maximum loss exceeds authorized risk",
        )
    applicability = entry.applicability
    terms = DerivExecutionTerms(
        environment=applicability.environment or "",
        account_scope=account_scope,
        account_currency=applicability.account_currency or "",
        underlying_symbol=applicability.symbol or "",
        contract_type=applicability.contract_family or "",
        stake=propositions.stake,
        stake_unit=ExecutionQuantityUnit.DERIV_STAKE,
        multiplier=propositions.multiplier,
        stop_loss_amount=propositions.stop_loss_amount,
        take_profit_amount=propositions.take_profit_amount,
        maximum_loss=propositions.maximum_loss,
        proof_id=entry.proof_id,
        material_hash=entry.candidate_material_hash,
        loss_model_id=entry.loss_model_id,
        loss_model_version=entry.loss_model_version,
        applicability=applicability,
    )
    return DerivExecutionTermsEvaluationResult(
        DerivExecutionTermsEvaluationState.VALIDATED_EXECUTION_TERMS,
        "Synthetic offline financial propositions validated",
        terms,
    )
