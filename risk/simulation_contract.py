"""JQE-owned synthetic contract semantics for offline simulation only."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR
from enum import Enum
import math


SIMULATION_PROOF_SCHEMA_VERSION = 1


class SimulationProofState(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"


@dataclass(frozen=True, slots=True)
class SimulationLossModelProof:
    schema_version: int
    loss_model_id: str
    loss_model_version: int
    evidence_id: str
    state: SimulationProofState
    broker: str
    contract_family: str
    quantity_basis: str
    stop_semantic: str

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("Unsupported simulation proof schema")
        if type(self.loss_model_version) is not int or self.loss_model_version <= 0:
            raise ValueError("Simulation loss-model version must be a positive integer")
        if not isinstance(self.state, SimulationProofState):
            raise ValueError("Simulation proof state is invalid")
        for name in ("loss_model_id", "evidence_id", "broker", "contract_family", "quantity_basis", "stop_semantic"):
            value = getattr(self, name)
            if type(value) is not str or not value.strip():
                raise ValueError(f"{name} must be a nonblank string")

    @property
    def identity(self) -> tuple[str, int, str]:
        return self.loss_model_id, self.loss_model_version, self.evidence_id


@dataclass(frozen=True, slots=True)
class SimulationContractSpecification:
    broker: str
    contract_family: str
    quantity_basis: str
    stop_semantic: str
    loss_model_id: str
    loss_model_version: int
    evidence_id: str
    stop_risk_per_unit: int | float | Decimal
    minimum_quantity: int | float | Decimal
    quantity_increment: int | float | Decimal

    def __post_init__(self) -> None:
        for name in ("broker", "contract_family", "quantity_basis", "stop_semantic", "loss_model_id", "evidence_id"):
            value = getattr(self, name)
            if type(value) is not str or not value.strip():
                raise ValueError(f"{name} must be a nonblank string")
        if type(self.loss_model_version) is not int or self.loss_model_version <= 0:
            raise ValueError("Simulation loss-model version must be a positive integer")
        for name in ("stop_risk_per_unit", "minimum_quantity", "quantity_increment"):
            value = getattr(self, name)
            if (
                type(value) not in (int, float, Decimal)
                or not math.isfinite(value)
                or value <= 0
            ):
                raise ValueError(f"{name} must be a positive finite number")


@dataclass(frozen=True, slots=True)
class SimulationProofRegistry:
    """Immutable registry populated only with JQE-owned synthetic evidence."""

    identities: frozenset[tuple[str, int, str]] = frozenset()

    def register(self, proof: SimulationLossModelProof) -> "SimulationProofRegistry":
        if proof.state is not SimulationProofState.VERIFIED:
            raise ValueError("Only verified simulation proofs may be registered")
        return SimulationProofRegistry(self.identities | {proof.identity})

    def unregister(self, proof: SimulationLossModelProof) -> "SimulationProofRegistry":
        return SimulationProofRegistry(self.identities - {proof.identity})


@dataclass(frozen=True, slots=True)
class SimulationQuantityCapability:
    stop_risk_authorizable: bool
    reason: str


def evaluate_simulation_capability(
    specification: SimulationContractSpecification,
    proof: SimulationLossModelProof | None,
    registry: SimulationProofRegistry,
) -> SimulationQuantityCapability:
    if proof is None:
        return SimulationQuantityCapability(False, "Synthetic loss-model proof is missing")
    if proof.state is not SimulationProofState.VERIFIED or proof.identity not in registry.identities:
        return SimulationQuantityCapability(False, "Synthetic loss-model proof is not registered")
    bindings = (
        (proof.broker, specification.broker),
        (proof.contract_family, specification.contract_family),
        (proof.quantity_basis, specification.quantity_basis),
        (proof.stop_semantic, specification.stop_semantic),
        (proof.loss_model_id, specification.loss_model_id),
        (proof.loss_model_version, specification.loss_model_version),
        (proof.evidence_id, specification.evidence_id),
    )
    if any(actual != expected for actual, expected in bindings):
        return SimulationQuantityCapability(False, "Synthetic proof applicability mismatch")
    return SimulationQuantityCapability(True, "JQE synthetic loss model is registered")


def floor_synthetic_quantity_exact(
    risk_amount: int | float | Decimal,
    specification: SimulationContractSpecification,
) -> Decimal | None:
    """Return the maximal synthetic quantity using exact conservative arithmetic."""
    if (
        type(risk_amount) not in (int, float, Decimal)
        or not math.isfinite(risk_amount)
        or risk_amount <= 0
    ):
        return None
    risk = risk_amount if isinstance(risk_amount, Decimal) else Decimal(str(risk_amount))
    stop_risk_per_unit = (
        specification.stop_risk_per_unit
        if isinstance(specification.stop_risk_per_unit, Decimal)
        else Decimal(str(specification.stop_risk_per_unit))
    )
    increment = (
        specification.quantity_increment
        if isinstance(specification.quantity_increment, Decimal)
        else Decimal(str(specification.quantity_increment))
    )
    raw = risk / stop_risk_per_unit
    quantity = (raw / increment).to_integral_value(rounding=ROUND_FLOOR) * increment
    minimum_quantity = (
        specification.minimum_quantity
        if isinstance(specification.minimum_quantity, Decimal)
        else Decimal(str(specification.minimum_quantity))
    )
    if quantity < minimum_quantity:
        return None

    # Flooring should already prove this invariant. One defensive decrement
    # keeps authorization fail-closed if boundary arithmetic ever changes.
    if quantity * stop_risk_per_unit > risk:
        quantity -= increment
        if (
            quantity < minimum_quantity
            or quantity * stop_risk_per_unit > risk
        ):
            return None
    return quantity


def floor_synthetic_quantity(
    risk_amount: float, specification: SimulationContractSpecification
) -> float | None:
    """Return a float DTO value only after exact Decimal flooring succeeds."""
    quantity = floor_synthetic_quantity_exact(risk_amount, specification)
    return None if quantity is None else float(quantity)


def canonical_simulation_proof() -> SimulationLossModelProof:
    return SimulationLossModelProof(
        schema_version=SIMULATION_PROOF_SCHEMA_VERSION,
        loss_model_id="jqe:simulation-linear-loss", loss_model_version=1,
        evidence_id="jqe-owned:simulation-contract-v1", state=SimulationProofState.VERIFIED,
        broker="simulation", contract_family="JQE_SYNTHETIC_LINEAR",
        quantity_basis="SIMULATION_UNITS", stop_semantic="PRICE_DISTANCE_CASH_PER_UNIT",
    )


def canonical_simulation_specification(
    stop_risk_per_unit: int | float | Decimal,
) -> SimulationContractSpecification:
    return SimulationContractSpecification(
        broker="simulation", contract_family="JQE_SYNTHETIC_LINEAR",
        quantity_basis="SIMULATION_UNITS", stop_semantic="PRICE_DISTANCE_CASH_PER_UNIT",
        loss_model_id="jqe:simulation-linear-loss", loss_model_version=1,
        evidence_id="jqe-owned:simulation-contract-v1", stop_risk_per_unit=stop_risk_per_unit,
        minimum_quantity=1e-12, quantity_increment=1e-12,
    )


def authoritative_simulation_registry() -> SimulationProofRegistry:
    return SimulationProofRegistry().register(canonical_simulation_proof())
