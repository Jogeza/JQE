"""Proof-of-architecture tests for JQE-owned synthetic loss semantics."""

from dataclasses import replace
from decimal import Decimal

import pytest

from broker.deriv_contract_spec import current_deriv_multiplier_specification, evaluate_deriv_quantity_capability
from broker.types import ExecutionQuantityUnit
from risk.position_sizing import authorize_execution_quantity
from risk.simulation_contract import (
    SimulationContractSpecification, SimulationLossModelProof, SimulationProofRegistry,
    SimulationProofState, authoritative_simulation_registry, canonical_simulation_proof,
    canonical_simulation_specification, evaluate_simulation_capability,
    floor_synthetic_quantity, floor_synthetic_quantity_exact,
)


def test_registered_synthetic_proof_authorizes_matching_capability() -> None:
    proof = canonical_simulation_proof()
    spec = canonical_simulation_specification(3.0)
    registry = SimulationProofRegistry().register(proof)
    assert evaluate_simulation_capability(spec, proof, registry).stop_risk_authorizable
    assert not evaluate_simulation_capability(spec, None, registry).stop_risk_authorizable
    assert not evaluate_simulation_capability(spec, proof, registry.unregister(proof)).stop_risk_authorizable


@pytest.mark.parametrize(
    "field,value",
    [("contract_family", "WRONG"), ("quantity_basis", "WRONG"),
     ("stop_semantic", "WRONG"), ("loss_model_version", 2)],
)
def test_proof_applicability_mismatches_fail_closed(field, value) -> None:
    proof = canonical_simulation_proof()
    spec = replace(canonical_simulation_specification(2.0), **{field: value})
    assert not evaluate_simulation_capability(
        spec, proof, authoritative_simulation_registry()
    ).stop_risk_authorizable


def test_self_declared_unregistered_proof_is_insufficient() -> None:
    proof = canonical_simulation_proof()
    assert not evaluate_simulation_capability(
        canonical_simulation_specification(1.0), proof, SimulationProofRegistry()
    ).stop_risk_authorizable


def test_wrong_proof_schema_is_rejected() -> None:
    with pytest.raises(ValueError, match="schema"):
        replace(canonical_simulation_proof(), schema_version=2)


@pytest.mark.parametrize("risk", [0, -1, float("nan"), float("inf")])
def test_invalid_risk_never_produces_quantity(risk) -> None:
    assert floor_synthetic_quantity(risk, canonical_simulation_specification(1.0)) is None


@pytest.mark.parametrize("stop_risk", [0, -1, float("nan"), float("inf")])
def test_invalid_stop_risk_is_rejected(stop_risk) -> None:
    with pytest.raises(ValueError):
        canonical_simulation_specification(stop_risk)


def test_conservative_rounding_and_independent_loss_invariant() -> None:
    spec = replace(
        canonical_simulation_specification(3.0), minimum_quantity=0.1,
        quantity_increment=0.1,
    )
    quantity = floor_synthetic_quantity(10.0, spec)
    assert quantity == 3.3
    assert quantity * spec.stop_risk_per_unit <= 10.0
    assert (quantity + spec.quantity_increment) * spec.stop_risk_per_unit > 10.0


@pytest.mark.parametrize(
    "risk,stop_risk,increment,expected",
    [
        (0.3, 3.0, 0.1, "0.1"),
        (0.7, 7.0, 0.1, "0.1"),
        (0.6, 3.0, 0.1, "0.2"),
        (1.0, 3.0, 0.1, "0.3"),
        (1.0, 8.0, 0.025, "0.125"),
    ],
)
def test_exact_decimal_boundaries_are_maximal_and_never_exceed_risk(
    risk, stop_risk, increment, expected
) -> None:
    spec = replace(
        canonical_simulation_specification(stop_risk),
        minimum_quantity=increment,
        quantity_increment=increment,
    )
    quantity = floor_synthetic_quantity_exact(risk, spec)
    assert quantity == Decimal(expected)

    risk_decimal = Decimal(str(risk))
    stop_decimal = Decimal(str(stop_risk))
    increment_decimal = Decimal(str(increment))
    assert quantity % increment_decimal == 0
    assert quantity * stop_decimal <= risk_decimal
    assert (quantity + increment_decimal) * stop_decimal > risk_decimal


def test_float_output_is_only_a_boundary_after_exact_authorization() -> None:
    decision = authorize_execution_quantity(
        broker="simulation", balance=30, risk_percent=1, entry=10, stop_loss=7
    )
    assert decision.quantity is not None
    assert decision.quantity.value == 0.1
    assert isinstance(decision.quantity.value, float)

    quantity_decimal = Decimal(str(decision.quantity.value))
    assert quantity_decimal * Decimal("3.0") == Decimal("0.3")
    assert quantity_decimal * Decimal("3.0") <= Decimal("0.3")
    assert decision.risk_verifiable is True


def test_exact_flooring_preserves_decimal_inputs() -> None:
    spec = replace(
        canonical_simulation_specification(Decimal("3.0")),
        minimum_quantity=Decimal("0.1"),
        quantity_increment=Decimal("0.1"),
    )
    assert floor_synthetic_quantity_exact(Decimal("0.3"), spec) == Decimal("0.1")


def test_minimum_quantity_above_budget_fails_closed() -> None:
    spec = replace(canonical_simulation_specification(10.0), minimum_quantity=1.0)
    assert floor_synthetic_quantity(5.0, spec) is None


def test_risk_engine_pipeline_emits_only_simulation_units_with_proven_loss() -> None:
    decision = authorize_execution_quantity(
        broker="simulation", balance=10_000, risk_percent=0.5, entry=100, stop_loss=92
    )
    assert decision.quantity is not None
    assert decision.quantity.unit is ExecutionQuantityUnit.SIMULATION_UNITS
    assert decision.expected_loss_at_stop <= decision.authorized_risk_amount


def test_real_deriv_registry_and_quantity_remain_fail_closed() -> None:
    capability = evaluate_deriv_quantity_capability(current_deriv_multiplier_specification())
    decision = authorize_execution_quantity(
        broker="deriv", balance=10_000, risk_percent=0.5, entry=100, stop_loss=92
    )
    assert capability.stop_risk_authorizable is False
    assert decision.quantity is None
    assert decision.risk_verifiable is False
