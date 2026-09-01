"""Offline-only tests for proof-bound Deriv financial execution terms."""

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone
from decimal import Decimal
import importlib.util
from pathlib import Path

import pytest

from broker.deriv_evidence_intake import DerivEvidenceClassification
from broker.deriv_execution_terms import (
    DerivExecutionTerms,
    DerivExecutionTermsEvaluationState,
    DerivSyntheticFinancialPropositions,
    evaluate_synthetic_deriv_execution_terms,
)
from broker.deriv_financial_semantics import (
    DerivCurrencyBinding,
    DerivFinancialOutput,
    DerivFinancialUnit,
    DerivOutputSemantic,
)
from broker.deriv_proof_consumption import (
    DerivProofConsumptionRequest,
    validate_authoritative_proof_for_capability,
)
from broker.deriv_proof_registry import DerivProofRegistryState, admit_deriv_proof_registry_entry
from broker.types import ExecutionQuantityUnit


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_registration = _load("jqe_terms_registration_fixtures", "test_deriv_proof_registration.py")
_semantics_fixtures = _load("jqe_terms_semantics_fixtures", "test_deriv_financial_semantics.py")
_EVALUATED_AT = datetime(2026, 10, 1, tzinfo=timezone.utc)


def _authoritative_semantics():
    scope = replace(
        _registration._SCOPE_P1,
        contract_family="MULTUP",
        symbol="R_100",
        environment="demo",
        account_currency="OFFLINE_TEST_CURRENCY",
    )
    return _semantics_fixtures._semantics(
        applicability=scope,
        take_profit_output=DerivFinancialOutput(
            DerivOutputSemantic.SYNTHETIC_MONETARY_PROFIT_FOR_SUPPLIED_INPUTS,
            DerivFinancialUnit.ACCOUNT_CURRENCY_AMOUNT,
            DerivCurrencyBinding.APPLICABILITY_ACCOUNT_CURRENCY,
            None,
            False,
            True,
        ),
        take_profit_semantic_id="offline:semantic:take-profit-amount",
        maximum_loss_output=DerivFinancialOutput(
            DerivOutputSemantic.SYNTHETIC_MAXIMUM_MONETARY_LOSS,
            DerivFinancialUnit.ACCOUNT_CURRENCY_AMOUNT,
            DerivCurrencyBinding.APPLICABILITY_ACCOUNT_CURRENCY,
            None,
            False,
            True,
        ),
        maximum_loss_semantic_id="offline:semantic:maximum-loss-amount",
        allowed_multiplier_values=(Decimal("7"),),
    )


def _consumed_proof():
    semantics = _authoritative_semantics()
    bundle = _semantics_fixtures._chain(semantics)
    eligibility, candidate, verification, assessment, decision, evidence = bundle
    request = replace(
        _registration._admission_request(),
        candidate_material_hash=semantics.material_hash,
        applicability=semantics.applicability,
        financial_semantics=semantics,
    )
    admitted = admit_deriv_proof_registry_entry(
        DerivProofRegistryState(),
        request,
        eligibility,
        candidate,
        verification,
        assessment,
        decision,
        evidence,
    )
    entry = admitted.registry.entries[0]
    consumption_request = DerivProofConsumptionRequest(
        schema_version=1,
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
        applicability=entry.applicability,
        loss_model_id=entry.loss_model_id,
        loss_model_version=entry.loss_model_version,
        evidence_source_id=entry.evidence_source_id,
        valid_from=entry.valid_from,
        valid_until=entry.valid_until,
        evaluated_at=_EVALUATED_AT,
        financial_semantics=semantics,
    )
    consumed = validate_authoritative_proof_for_capability(
        admitted.registry, consumption_request
    )
    return consumed, semantics


def _terms(**changes):
    proof, _ = _consumed_proof()
    entry = proof.entry
    assert entry is not None
    values = {
        "environment": "demo",
        "account_scope": "offline:test-account",
        "account_currency": "OFFLINE_TEST_CURRENCY",
        "underlying_symbol": "R_100",
        "contract_type": "MULTUP",
        "stake": Decimal("10"),
        "stake_unit": ExecutionQuantityUnit.DERIV_STAKE,
        "multiplier": Decimal("7"),
        "stop_loss_amount": Decimal("2"),
        "take_profit_amount": Decimal("3"),
        "maximum_loss": Decimal("2"),
        "proof_id": entry.proof_id,
        "material_hash": entry.candidate_material_hash,
        "loss_model_id": entry.loss_model_id,
        "loss_model_version": entry.loss_model_version,
        "applicability": entry.applicability,
    }
    values.update(changes)
    return DerivExecutionTerms(**values)


def _propositions(**changes):
    values = {
        "classification": DerivEvidenceClassification.SYNTHETIC_TEST_ONLY,
        "stake": Decimal("10"),
        "multiplier": Decimal("7"),
        "stop_loss_amount": Decimal("2"),
        "take_profit_amount": Decimal("3"),
        "maximum_loss": Decimal("2"),
    }
    values.update(changes)
    return DerivSyntheticFinancialPropositions(**values)


def test_valid_terms_are_immutable_decimal_financial_values() -> None:
    terms = _terms()
    assert terms.stake_unit is ExecutionQuantityUnit.DERIV_STAKE
    assert all(
        type(getattr(terms, name)) is Decimal
        for name in (
            "stake", "multiplier", "stop_loss_amount", "take_profit_amount", "maximum_loss"
        )
    )
    with pytest.raises(FrozenInstanceError):
        terms.stake = Decimal("11")


@pytest.mark.parametrize(
    "field,value",
    [
        ("stake", Decimal("0")),
        ("stake", Decimal("-1")),
        ("multiplier", Decimal("0")),
        ("multiplier", Decimal("-1")),
        ("stop_loss_amount", Decimal("-1")),
        ("take_profit_amount", Decimal("-1")),
        ("maximum_loss", Decimal("-1")),
        ("stake", Decimal("NaN")),
        ("stake", Decimal("Infinity")),
        ("stake", True),
    ],
)
def test_invalid_financial_values_are_rejected(field, value) -> None:
    with pytest.raises(ValueError):
        _terms(**{field: value})


@pytest.mark.parametrize(
    "changes",
    [
        {"account_currency": ""},
        {"environment": ""},
        {"underlying_symbol": ""},
        {"contract_type": ""},
        {"proof_id": ""},
        {"material_hash": "bad"},
        {"loss_model_id": ""},
        {"loss_model_version": 0},
    ],
)
def test_missing_or_invalid_identity_is_rejected(changes) -> None:
    with pytest.raises(ValueError):
        _terms(**changes)


def test_market_prices_are_not_part_of_financial_terms() -> None:
    fields = DerivExecutionTerms.__dataclass_fields__
    assert not {"entry_price", "stop_price", "take_profit_price"} & fields.keys()
    assert {"stop_loss_amount", "take_profit_amount"} <= fields.keys()


def test_currency_environment_symbol_and_contract_must_match_proof() -> None:
    for changes in (
        {"account_currency": "OTHER"},
        {"environment": "real"},
        {"underlying_symbol": "OTHER"},
        {"contract_type": "MULTDOWN"},
    ):
        with pytest.raises(ValueError, match="applicability"):
            _terms(**changes)


def test_stop_and_take_profit_are_distinct_monetary_outputs() -> None:
    terms = _terms(stop_loss_amount=Decimal("1.25"), take_profit_amount=Decimal("4.50"))
    assert terms.stop_loss_amount == Decimal("1.25")
    assert terms.take_profit_amount == Decimal("4.50")


def test_synthetic_terms_validate_when_maximum_loss_is_within_risk() -> None:
    proof, semantics = _consumed_proof()
    result = evaluate_synthetic_deriv_execution_terms(
        proof=proof,
        semantics=semantics,
        propositions=_propositions(maximum_loss=Decimal("2")),
        authorized_risk_amount=Decimal("2"),
    )
    assert result.state is DerivExecutionTermsEvaluationState.VALIDATED_EXECUTION_TERMS
    assert result.terms is not None


def test_maximum_loss_above_risk_fails_closed() -> None:
    proof, semantics = _consumed_proof()
    result = evaluate_synthetic_deriv_execution_terms(
        proof=proof,
        semantics=semantics,
        propositions=_propositions(maximum_loss=Decimal("2.01")),
        authorized_risk_amount=Decimal("2"),
    )
    assert result.state is DerivExecutionTermsEvaluationState.RISK_LIMIT_EXCEEDED
    assert result.terms is None


def test_missing_maximum_loss_fails_closed() -> None:
    proof, semantics = _consumed_proof()
    result = evaluate_synthetic_deriv_execution_terms(
        proof=proof,
        semantics=semantics,
        propositions=_propositions(maximum_loss=None),
        authorized_risk_amount=Decimal("2"),
    )
    assert result.state is DerivExecutionTermsEvaluationState.FINANCIAL_INPUT_INVALID


def test_production_path_remains_model_unsupported() -> None:
    proof, semantics = _consumed_proof()
    result = evaluate_synthetic_deriv_execution_terms(
        proof=proof,
        semantics=semantics,
        propositions=None,
        authorized_risk_amount=Decimal("2"),
    )
    assert (
        result.state
        is DerivExecutionTermsEvaluationState.PROOF_VALID_BUT_MODEL_UNSUPPORTED
    )
    assert result.terms is None
