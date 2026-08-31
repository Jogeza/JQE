"""Offline Deriv contract facts and fail-closed quantity capability checks.

This module contains no discovery or pricing logic.  Values describe evidence
already held by JQE; ``None`` and ``UNKNOWN`` deliberately remain unknown.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
from typing import Any


DERIV_CONTRACT_SPEC_SCHEMA_VERSION = 1
DERIV_LOSS_MODEL_PROOF_SCHEMA_VERSION = 1
# Populated only by a future checkpoint that independently validates an
# authoritative equation artifact.  Metadata construction cannot add entries.
_AUTHORIZED_LOSS_MODEL_PROOFS: frozenset[tuple[str, int, str]] = frozenset()


class DerivSpecificationVerification(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    PARTIALLY_VERIFIED = "PARTIALLY_VERIFIED"
    VERIFIED = "VERIFIED"


class DerivSupportState(str, Enum):
    UNKNOWN = "UNKNOWN"
    UNSUPPORTED = "UNSUPPORTED"
    SUPPORTED = "SUPPORTED"


class DerivProofValidation(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"


def _required_text(name: str, value: Any) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{name} must be a nonblank string")
    return value.strip()


def _optional_text(name: str, value: Any) -> None:
    if value is not None:
        _required_text(name, value)


def _optional_positive_number(name: str, value: Any) -> None:
    if value is None:
        return
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a positive finite number")


@dataclass(frozen=True, slots=True)
class DerivLossModelProof:
    """Identity and applicability of an independently validated loss proof.

    This is not a loss equation.  A future evidence-ingestion checkpoint must
    construct it only after validating the referenced proof independently.
    """

    proof_schema_version: int
    loss_model_id: str
    loss_model_version: int
    evidence_source_id: str
    validation_state: DerivProofValidation
    broker: str
    contract_family: str
    quantity_basis: str
    stop_loss_semantic_id: str
    multiplier_semantics_id: str

    def __post_init__(self) -> None:
        if type(self.proof_schema_version) is not int:
            raise ValueError("proof_schema_version must be a strict integer")
        if self.proof_schema_version != DERIV_LOSS_MODEL_PROOF_SCHEMA_VERSION:
            raise ValueError("unsupported loss-model proof schema")
        if type(self.loss_model_version) is not int or self.loss_model_version <= 0:
            raise ValueError("loss_model_version must be a positive strict integer")
        if not isinstance(self.validation_state, DerivProofValidation):
            raise ValueError("validation_state is invalid")
        for name in (
            "loss_model_id", "evidence_source_id", "broker", "contract_family",
            "quantity_basis", "stop_loss_semantic_id", "multiplier_semantics_id",
        ):
            _required_text(name, getattr(self, name))


@dataclass(frozen=True, slots=True)
class DerivContractSpecification:
    """Versioned broker facts needed to prove Deriv loss at a stop."""

    schema_version: int = DERIV_CONTRACT_SPEC_SCHEMA_VERSION
    broker: str = "deriv"
    contract_type: str | None = None
    contract_availability: DerivSupportState = DerivSupportState.UNKNOWN
    symbol: str | None = None
    symbol_support: DerivSupportState = DerivSupportState.UNKNOWN
    duration_requirements_id: str | None = None
    quantity_basis: str | None = None
    account_currency: str | None = None
    currency_treatment_id: str | None = None
    multiplier: float | None = None
    multiplier_semantics_id: str | None = None
    multiplier_is_placeholder: bool = False
    minimum_stake: float | None = None
    stake_precision: int | None = None
    stake_increment: float | None = None
    stop_loss_semantic_id: str | None = None
    supported_limit_order_fields: frozenset[str] = frozenset()
    loss_model_id: str | None = None
    loss_model_version: int | None = None
    evidence_source_id: str | None = None
    loss_model_proof: DerivLossModelProof | None = None
    verification_state: DerivSpecificationVerification = (
        DerivSpecificationVerification.UNVERIFIED
    )

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int:
            raise ValueError("schema_version must be a strict integer")
        if not isinstance(self.symbol_support, DerivSupportState):
            raise ValueError("symbol_support is invalid")
        if not isinstance(self.contract_availability, DerivSupportState):
            raise ValueError("contract_availability is invalid")
        if not isinstance(self.verification_state, DerivSpecificationVerification):
            raise ValueError("verification_state is invalid")
        for name in (
            "broker", "contract_type", "symbol", "duration_requirements_id",
            "quantity_basis", "account_currency", "currency_treatment_id",
            "multiplier_semantics_id", "stop_loss_semantic_id", "loss_model_id",
            "evidence_source_id",
        ):
            _optional_text(name, getattr(self, name))
        _optional_positive_number("multiplier", self.multiplier)
        _optional_positive_number("minimum_stake", self.minimum_stake)
        _optional_positive_number("stake_increment", self.stake_increment)
        if self.stake_precision is not None and (
            type(self.stake_precision) is not int or self.stake_precision < 0
        ):
            raise ValueError("stake_precision must be a nonnegative strict integer")
        if self.loss_model_version is not None and (
            type(self.loss_model_version) is not int or self.loss_model_version <= 0
        ):
            raise ValueError("loss_model_version must be a positive strict integer")
        if type(self.multiplier_is_placeholder) is not bool:
            raise ValueError("multiplier_is_placeholder must be boolean")
        if not isinstance(self.supported_limit_order_fields, frozenset) or any(
            type(value) is not str or not value.strip()
            for value in self.supported_limit_order_fields
        ):
            raise ValueError("supported_limit_order_fields must contain nonblank strings")
        if self.loss_model_proof is not None and not isinstance(
            self.loss_model_proof, DerivLossModelProof
        ):
            raise ValueError("loss_model_proof is invalid")


@dataclass(frozen=True, slots=True)
class DerivQuantityCapability:
    stop_risk_authorizable: bool
    missing_requirements: tuple[str, ...]

    @property
    def reason(self) -> str:
        if self.stop_risk_authorizable:
            return "Deriv loss-model proof is verified"
        return "Deriv loss-model proof is not verified: " + "; ".join(
            self.missing_requirements
        )


def evaluate_deriv_quantity_capability(
    specification: DerivContractSpecification,
) -> DerivQuantityCapability:
    """Purely assess whether offline facts can prove stop-risk authorization."""
    missing: list[str] = []
    if specification.schema_version != DERIV_CONTRACT_SPEC_SCHEMA_VERSION:
        missing.append("unsupported specification schema")
    if specification.broker != "deriv":
        missing.append("broker identity")
    if specification.contract_type not in {"MULTUP", "MULTDOWN"}:
        missing.append("supported contract type")
    if specification.contract_availability is not DerivSupportState.SUPPORTED:
        missing.append("verified contract availability")
    if specification.symbol_support is not DerivSupportState.SUPPORTED:
        missing.append("verified symbol eligibility")
    if specification.quantity_basis != "stake":
        missing.append("stake quantity basis")
    if not specification.duration_requirements_id:
        missing.append("duration requirements")
    if not specification.account_currency or not specification.currency_treatment_id:
        missing.append("account-currency treatment")
    if (
        specification.multiplier is None
        or not specification.multiplier_semantics_id
        or specification.multiplier_is_placeholder
    ):
        missing.append("verified multiplier-loss relationship")
    if specification.minimum_stake is None:
        missing.append("minimum stake")
    if (
        specification.stake_precision is None
    ):
        missing.append("stake precision")
    if specification.stake_increment is None:
        missing.append("stake increment")
    if (
        not specification.stop_loss_semantic_id
        or "stop_loss" not in specification.supported_limit_order_fields
    ):
        missing.append("absolute stop-loss semantics")
    if not specification.loss_model_id or specification.loss_model_version is None:
        missing.append("versioned loss equation")
    if not specification.evidence_source_id:
        missing.append("authoritative evidence source")
    proof = specification.loss_model_proof
    if proof is None or proof.validation_state is not DerivProofValidation.VERIFIED:
        missing.append("independently validated loss-model proof")
    elif (
        proof.loss_model_id != specification.loss_model_id
        or proof.loss_model_version != specification.loss_model_version
        or proof.evidence_source_id != specification.evidence_source_id
        or proof.broker != specification.broker
        or proof.contract_family != specification.contract_type
        or proof.quantity_basis != specification.quantity_basis
        or proof.stop_loss_semantic_id != specification.stop_loss_semantic_id
        or proof.multiplier_semantics_id != specification.multiplier_semantics_id
    ):
        missing.append("loss-model proof applicability")
    elif (
        proof.loss_model_id,
        proof.loss_model_version,
        proof.evidence_source_id,
    ) not in _AUTHORIZED_LOSS_MODEL_PROOFS:
        missing.append("authoritative proof registration")
    if specification.verification_state is not DerivSpecificationVerification.VERIFIED:
        missing.append("fully verified specification state")
    return DerivQuantityCapability(not missing, tuple(missing))


def current_deriv_multiplier_specification() -> DerivContractSpecification:
    """Describe the current gateway intent without promoting it to authority."""
    return DerivContractSpecification(
        contract_type=None,
        symbol=None,
        symbol_support=DerivSupportState.UNKNOWN,
        quantity_basis="stake",
        multiplier=100.0,
        multiplier_is_placeholder=True,
        supported_limit_order_fields=frozenset({"stop_loss", "take_profit"}),
        verification_state=DerivSpecificationVerification.UNVERIFIED,
    )
