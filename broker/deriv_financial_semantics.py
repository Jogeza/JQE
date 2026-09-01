"""Declarative governance for Deriv financial semantics; never equation execution."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
import hashlib
import json
import re
from typing import Any

from broker.deriv_evidence import DerivEvidenceApplicability


DERIV_FINANCIAL_SEMANTICS_SCHEMA_VERSION = 1
_SHA256_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")


def _text(name: str, value: Any) -> None:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{name} must be a nonblank string")


class DerivEquationFamily(str, Enum):
    SYNTHETIC_LINEAR_PRODUCT = "SYNTHETIC_LINEAR_PRODUCT"


class DerivOperandRole(str, Enum):
    FACTOR = "FACTOR"
    RATE = "RATE"
    BASE = "BASE"


class DerivFinancialUnit(str, Enum):
    ACCOUNT_CURRENCY_AMOUNT = "ACCOUNT_CURRENCY_AMOUNT"
    STAKE_CURRENCY_AMOUNT = "STAKE_CURRENCY_AMOUNT"
    PRICE = "PRICE"
    PRICE_DISTANCE = "PRICE_DISTANCE"
    RATIO = "RATIO"
    MULTIPLIER = "MULTIPLIER"
    CONTRACT_QUANTITY = "CONTRACT_QUANTITY"
    PERCENTAGE = "PERCENTAGE"


class DerivNumericDomain(str, Enum):
    POSITIVE = "POSITIVE"
    NONNEGATIVE = "NONNEGATIVE"
    SIGNED = "SIGNED"
    UNKNOWN = "UNKNOWN"


class DerivOutputSemantic(str, Enum):
    SYNTHETIC_MONETARY_LOSS_FOR_SUPPLIED_INPUTS = (
        "SYNTHETIC_MONETARY_LOSS_FOR_SUPPLIED_INPUTS"
    )
    SYNTHETIC_MAXIMUM_MONETARY_LOSS = "SYNTHETIC_MAXIMUM_MONETARY_LOSS"


class DerivCurrencyBinding(str, Enum):
    APPLICABILITY_ACCOUNT_CURRENCY = "APPLICABILITY_ACCOUNT_CURRENCY"
    EXPLICIT_CURRENCY = "EXPLICIT_CURRENCY"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class DerivRoundingMode(str, Enum):
    NONE = "NONE"
    ROUND_FLOOR = "ROUND_FLOOR"
    ROUND_CEILING = "ROUND_CEILING"
    ROUND_HALF_EVEN = "ROUND_HALF_EVEN"


class DerivRoundingStage(str, Enum):
    NONE = "NONE"
    EACH_OPERATION = "EACH_OPERATION"
    FINAL_OUTPUT = "FINAL_OUTPUT"


@dataclass(frozen=True, slots=True)
class DerivFinancialOperand:
    operand_id: str
    semantic_id: str
    unit: DerivFinancialUnit
    role: DerivOperandRole
    position: int
    required: bool
    domain: DerivNumericDomain
    lower_bound: Decimal | None = None
    upper_bound: Decimal | None = None
    zero_allowed: bool = False
    currency_bound: bool = False
    multiplier_bound: bool = False

    def __post_init__(self) -> None:
        _text("operand_id", self.operand_id)
        _text("semantic_id", self.semantic_id)
        if not isinstance(self.unit, DerivFinancialUnit):
            raise ValueError("operand unit is invalid")
        if not isinstance(self.role, DerivOperandRole):
            raise ValueError("operand role is invalid")
        if type(self.position) is not int or self.position < 0:
            raise ValueError("operand position must be a nonnegative strict integer")
        for name in ("required", "zero_allowed", "currency_bound", "multiplier_bound"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be boolean")
        if not isinstance(self.domain, DerivNumericDomain):
            raise ValueError("operand domain is invalid")
        for name in ("lower_bound", "upper_bound"):
            value = getattr(self, name)
            if value is not None and (
                type(value) is not Decimal or not value.is_finite()
            ):
                raise ValueError(f"{name} must be a finite Decimal")
        if (
            self.lower_bound is not None
            and self.upper_bound is not None
            and self.lower_bound > self.upper_bound
        ):
            raise ValueError("operand lower bound cannot exceed upper bound")
        if self.domain is DerivNumericDomain.POSITIVE and self.zero_allowed:
            raise ValueError("positive operands cannot allow zero")


@dataclass(frozen=True, slots=True)
class DerivFinancialOutput:
    semantic: DerivOutputSemantic
    unit: DerivFinancialUnit
    currency_binding: DerivCurrencyBinding
    explicit_currency: str | None
    signed: bool
    zero_allowed: bool

    def __post_init__(self) -> None:
        if not isinstance(self.semantic, DerivOutputSemantic):
            raise ValueError("output semantic is invalid")
        if not isinstance(self.unit, DerivFinancialUnit):
            raise ValueError("output unit is invalid")
        if not isinstance(self.currency_binding, DerivCurrencyBinding):
            raise ValueError("output currency binding is invalid")
        if self.currency_binding is DerivCurrencyBinding.EXPLICIT_CURRENCY:
            _text("explicit_currency", self.explicit_currency)
        elif self.explicit_currency is not None:
            raise ValueError("explicit currency is inconsistent with currency binding")
        if type(self.signed) is not bool or type(self.zero_allowed) is not bool:
            raise ValueError("output sign and zero policies must be boolean")


@dataclass(frozen=True, slots=True)
class DerivRoundingPolicy:
    required: bool
    precision: int | None
    mode: DerivRoundingMode
    stage: DerivRoundingStage

    def __post_init__(self) -> None:
        if type(self.required) is not bool:
            raise ValueError("rounding required must be boolean")
        if not isinstance(self.mode, DerivRoundingMode) or not isinstance(
            self.stage, DerivRoundingStage
        ):
            raise ValueError("rounding mode or stage is invalid")
        if self.required:
            if type(self.precision) is not int or self.precision < 0:
                raise ValueError("required rounding needs nonnegative precision")
            if self.mode is DerivRoundingMode.NONE or self.stage is DerivRoundingStage.NONE:
                raise ValueError("required rounding needs explicit mode and stage")
        elif (
            self.precision is not None
            or self.mode is not DerivRoundingMode.NONE
            or self.stage is not DerivRoundingStage.NONE
        ):
            raise ValueError("disabled rounding cannot define precision, mode, or stage")


@dataclass(frozen=True, slots=True)
class DerivFinancialSemanticsSpecification:
    schema_version: int
    semantic_id: str
    semantic_version: int
    equation_family: DerivEquationFamily
    equation_identity_hash: str
    operands: tuple[DerivFinancialOperand, ...]
    output: DerivFinancialOutput
    rounding: DerivRoundingPolicy
    domain_constraint_ids: tuple[str, ...]
    applicability: DerivEvidenceApplicability
    contract_family: str
    quantity_basis_semantic_id: str
    stop_semantic_id: str
    multiplier_semantic_id: str

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("unsupported financial-semantics schema version")
        _text("semantic_id", self.semantic_id)
        if type(self.semantic_version) is not int or self.semantic_version <= 0:
            raise ValueError("semantic_version must be a positive strict integer")
        if not isinstance(self.equation_family, DerivEquationFamily):
            raise ValueError("equation family is invalid")
        if type(self.equation_identity_hash) is not str or not _SHA256_PATTERN.fullmatch(
            self.equation_identity_hash
        ):
            raise ValueError("equation identity must be a lowercase SHA-256 ID")
        if type(self.operands) is not tuple or not self.operands or any(
            not isinstance(item, DerivFinancialOperand) for item in self.operands
        ):
            raise ValueError("operands must be a nonempty immutable typed tuple")
        ids = tuple(item.operand_id for item in self.operands)
        positions = tuple(item.position for item in self.operands)
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate operand IDs are not allowed")
        if positions != tuple(range(len(self.operands))):
            raise ValueError("operand positions must be ordered and contiguous")
        if not isinstance(self.output, DerivFinancialOutput):
            raise ValueError("output is invalid")
        if not isinstance(self.rounding, DerivRoundingPolicy):
            raise ValueError("rounding policy is invalid")
        if type(self.domain_constraint_ids) is not tuple or any(
            type(value) is not str or not value.strip()
            for value in self.domain_constraint_ids
        ):
            raise ValueError("domain constraints must be an immutable text tuple")
        if self.domain_constraint_ids != tuple(sorted(set(self.domain_constraint_ids))):
            raise ValueError("domain constraints must be unique and deterministically ordered")
        if not isinstance(self.applicability, DerivEvidenceApplicability):
            raise ValueError("applicability is invalid")
        for name in (
            "contract_family",
            "quantity_basis_semantic_id",
            "stop_semantic_id",
            "multiplier_semantic_id",
        ):
            _text(name, getattr(self, name))
        if (
            self.contract_family != self.applicability.contract_family
            or self.quantity_basis_semantic_id != self.applicability.quantity_basis
            or self.stop_semantic_id != self.applicability.stop_loss_semantic_id
            or self.multiplier_semantic_id != self.applicability.multiplier_semantics_id
        ):
            raise ValueError("financial semantics conflict with exact applicability")

    @property
    def material_hash(self) -> str:
        return canonical_financial_semantics_hash(self)


def _decimal(value: Decimal | None) -> str | None:
    return None if value is None else value.to_eng_string()


def canonical_financial_semantics_hash(
    specification: DerivFinancialSemanticsSpecification,
) -> str:
    """Return deterministic identity without executing the declared equation."""
    if not isinstance(specification, DerivFinancialSemanticsSpecification):
        raise ValueError("specification is invalid")
    payload = {
        "schema_version": specification.schema_version,
        "semantic_id": specification.semantic_id,
        "semantic_version": specification.semantic_version,
        "equation_family": specification.equation_family.value,
        "equation_identity_hash": specification.equation_identity_hash,
        "operands": [
            {
                "operand_id": item.operand_id,
                "semantic_id": item.semantic_id,
                "unit": item.unit.value,
                "role": item.role.value,
                "position": item.position,
                "required": item.required,
                "domain": item.domain.value,
                "lower_bound": _decimal(item.lower_bound),
                "upper_bound": _decimal(item.upper_bound),
                "zero_allowed": item.zero_allowed,
                "currency_bound": item.currency_bound,
                "multiplier_bound": item.multiplier_bound,
            }
            for item in specification.operands
        ],
        "output": {
            "semantic": specification.output.semantic.value,
            "unit": specification.output.unit.value,
            "currency_binding": specification.output.currency_binding.value,
            "explicit_currency": specification.output.explicit_currency,
            "signed": specification.output.signed,
            "zero_allowed": specification.output.zero_allowed,
        },
        "rounding": {
            "required": specification.rounding.required,
            "precision": specification.rounding.precision,
            "mode": specification.rounding.mode.value,
            "stage": specification.rounding.stage.value,
        },
        "domain_constraint_ids": specification.domain_constraint_ids,
        "applicability": {
            name: getattr(specification.applicability, name)
            for name in specification.applicability.__dataclass_fields__
        },
        "contract_family": specification.contract_family,
        "quantity_basis_semantic_id": specification.quantity_basis_semantic_id,
        "stop_semantic_id": specification.stop_semantic_id,
        "multiplier_semantic_id": specification.multiplier_semantic_id,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()
