"""Offline tests for fail-closed Deriv contract capability evidence."""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import patch

import pytest

from broker.deriv_contract_spec import (
    DerivContractSpecification,
    DerivLossModelProof,
    DerivProofValidation,
    DerivSpecificationVerification,
    DerivSupportState,
    current_deriv_multiplier_specification,
    evaluate_deriv_quantity_capability,
)


def _complete_spec() -> DerivContractSpecification:
    return DerivContractSpecification(
        contract_type="MULTUP", contract_availability=DerivSupportState.SUPPORTED,
        symbol="R_100",
        symbol_support=DerivSupportState.SUPPORTED, quantity_basis="stake",
        duration_requirements_id="evidence:no-duration-v1",
        account_currency="USD", currency_treatment_id="evidence:currency-v1",
        multiplier=100, multiplier_semantics_id="evidence:multiplier-v1",
        minimum_stake=1.0, stake_precision=2, stake_increment=0.01,
        stop_loss_semantic_id="evidence:absolute-underlying-stop-v1",
        supported_limit_order_fields=frozenset({"stop_loss", "take_profit"}),
        loss_model_id="evidence:multipliers-stop-loss", loss_model_version=1,
        evidence_source_id="authoritative:test-fixture",
        verification_state=DerivSpecificationVerification.VERIFIED,
    )


def test_current_spec_is_not_quantity_authorizable() -> None:
    decision = evaluate_deriv_quantity_capability(current_deriv_multiplier_specification())
    assert decision.stop_risk_authorizable is False
    assert "versioned loss equation" in decision.missing_requirements


@pytest.mark.parametrize(
    "changes,requirement",
    [
        ({"loss_model_id": None}, "versioned loss equation"),
        ({"multiplier_semantics_id": None}, "verified multiplier-loss relationship"),
        ({"stop_loss_semantic_id": None}, "absolute stop-loss semantics"),
        ({"stake_precision": None}, "stake precision"),
        ({"minimum_stake": None}, "minimum stake"),
        ({"stake_increment": None}, "stake increment"),
        ({"symbol_support": DerivSupportState.UNKNOWN}, "verified symbol eligibility"),
        ({"symbol_support": DerivSupportState.UNSUPPORTED}, "verified symbol eligibility"),
        ({"contract_type": "CALL"}, "supported contract type"),
        ({"contract_availability": DerivSupportState.UNKNOWN}, "verified contract availability"),
        ({"duration_requirements_id": None}, "duration requirements"),
        ({"currency_treatment_id": None}, "account-currency treatment"),
    ],
)
def test_missing_contract_fact_fails_closed(changes, requirement) -> None:
    decision = evaluate_deriv_quantity_capability(replace(_complete_spec(), **changes))
    assert decision.stop_risk_authorizable is False
    assert requirement in decision.missing_requirements


def test_placeholder_multiplier_never_counts_as_evidence() -> None:
    decision = evaluate_deriv_quantity_capability(
        replace(_complete_spec(), multiplier_is_placeholder=True)
    )
    assert "verified multiplier-loss relationship" in decision.missing_requirements


def test_partial_verification_and_future_schema_fail_closed() -> None:
    partial = replace(
        _complete_spec(),
        verification_state=DerivSpecificationVerification.PARTIALLY_VERIFIED,
    )
    future = replace(_complete_spec(), schema_version=99)
    assert not evaluate_deriv_quantity_capability(partial).stop_risk_authorizable
    assert "unsupported specification schema" in evaluate_deriv_quantity_capability(
        future
    ).missing_requirements


@pytest.mark.parametrize("schema", [True, False, 1.0, "1", None])
def test_malformed_schema_type_is_rejected(schema) -> None:
    with pytest.raises(ValueError, match="strict integer"):
        replace(_complete_spec(), schema_version=schema)


@pytest.mark.parametrize("version", [True, False, 1.0, "1", None])
def test_malformed_proof_schema_type_is_rejected(version) -> None:
    with pytest.raises(ValueError, match="strict integer"):
        DerivLossModelProof(
            proof_schema_version=version,
            loss_model_id="model", loss_model_version=1,
            evidence_source_id="source", validation_state=DerivProofValidation.UNVERIFIED,
            broker="deriv", contract_family="MULTUP", quantity_basis="stake",
            stop_loss_semantic_id="stop", multiplier_semantics_id="multiplier",
        )


def test_unsupported_future_integer_proof_schema_is_rejected() -> None:
    with pytest.raises(ValueError, match="unsupported loss-model proof schema"):
        DerivLossModelProof(
            proof_schema_version=2,
            loss_model_id="model", loss_model_version=1,
            evidence_source_id="source", validation_state=DerivProofValidation.UNVERIFIED,
            broker="deriv", contract_family="MULTUP", quantity_basis="stake",
            stop_loss_semantic_id="stop", multiplier_semantics_id="multiplier",
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("minimum_stake", 0), ("minimum_stake", -1),
        ("minimum_stake", "1"), ("minimum_stake", True),
        ("minimum_stake", float("nan")), ("minimum_stake", float("inf")),
        ("minimum_stake", float("-inf")), ("minimum_stake", []),
        ("stake_increment", 0), ("stake_increment", -1),
        ("stake_increment", "0.01"), ("stake_increment", {}),
        ("stake_precision", True), ("stake_precision", 1.5),
        ("multiplier", complex(1, 2)),
    ],
)
def test_malformed_numeric_facts_are_rejected(field, value) -> None:
    with pytest.raises(ValueError):
        replace(_complete_spec(), **{field: value})


@pytest.mark.parametrize(
    "field", ["loss_model_id", "evidence_source_id", "broker", "contract_type",
              "quantity_basis", "account_currency", "stop_loss_semantic_id"]
)
@pytest.mark.parametrize("value", ["", "   ", 123, [], {}])
def test_malformed_identifiers_are_rejected(field, value) -> None:
    with pytest.raises(ValueError, match="nonblank string"):
        replace(_complete_spec(), **{field: value})


def test_capability_check_has_no_network_or_gateway_side_effects() -> None:
    with patch("broker.deriv_gateway.websockets.connect") as connect, patch(
        "broker.deriv_gateway.DerivGateway"
    ) as gateway:
        decision = evaluate_deriv_quantity_capability(
            current_deriv_multiplier_specification()
        )
    connect.assert_not_called()
    gateway.assert_not_called()
    assert decision.stop_risk_authorizable is False


def test_verified_metadata_without_proof_cannot_authorize() -> None:
    decision = evaluate_deriv_quantity_capability(_complete_spec())
    assert decision.stop_risk_authorizable is False
    assert "independently validated loss-model proof" in decision.missing_requirements


def test_proof_artifact_is_structurally_bound_to_specification() -> None:
    proof = DerivLossModelProof(
        proof_schema_version=1, loss_model_id="evidence:multipliers-stop-loss",
        loss_model_version=1, evidence_source_id="authoritative:test-fixture",
        validation_state=DerivProofValidation.UNVERIFIED, broker="deriv",
        contract_family="MULTUP", quantity_basis="stake",
        stop_loss_semantic_id="evidence:absolute-underlying-stop-v1",
        multiplier_semantics_id="evidence:multiplier-v1",
    )
    decision = evaluate_deriv_quantity_capability(
        replace(_complete_spec(), loss_model_proof=proof)
    )
    assert decision.stop_risk_authorizable is False
    assert "independently validated loss-model proof" in decision.missing_requirements


def test_self_declared_verified_proof_is_not_authoritative() -> None:
    proof = DerivLossModelProof(
        proof_schema_version=1, loss_model_id="evidence:multipliers-stop-loss",
        loss_model_version=1, evidence_source_id="authoritative:test-fixture",
        validation_state=DerivProofValidation.VERIFIED, broker="deriv",
        contract_family="MULTUP", quantity_basis="stake",
        stop_loss_semantic_id="evidence:absolute-underlying-stop-v1",
        multiplier_semantics_id="evidence:multiplier-v1",
    )
    decision = evaluate_deriv_quantity_capability(
        replace(_complete_spec(), loss_model_proof=proof)
    )
    assert decision.stop_risk_authorizable is False
    assert "authoritative proof registration" in decision.missing_requirements
