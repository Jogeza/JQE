"""Governance-only tests for synthetic Deriv financial semantics."""

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone
from decimal import Decimal
import importlib.util
from pathlib import Path

import pytest

from broker.deriv_evidence import DerivEvidenceRegistry
from broker.deriv_financial_semantics import (
    DerivCurrencyBinding,
    DerivEquationFamily,
    DerivFinancialOperand,
    DerivFinancialOutput,
    DerivFinancialSemanticsSpecification,
    DerivFinancialUnit,
    DerivNumericDomain,
    DerivOperandRole,
    DerivOutputSemantic,
    DerivRoundingMode,
    DerivRoundingPolicy,
    DerivRoundingStage,
)
from broker.deriv_proof_consumption import (
    DerivProofConsumptionRequest,
    DerivProofConsumptionState,
    validate_authoritative_proof_for_capability,
)
from broker.deriv_proof_registration import (
    DerivProofRegistrationReason,
    validate_deriv_proof_registration_eligibility,
)
from broker.deriv_proof_registry import (
    admit_deriv_proof_registry_entry,
)


_spec = importlib.util.spec_from_file_location(
    "jqe_semantic_registration_fixtures",
    Path(__file__).with_name("test_deriv_proof_registration.py"),
)
assert _spec is not None and _spec.loader is not None
_fixtures = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fixtures)


def _semantics(**changes):
    scope = changes.pop(
        "applicability",
        replace(
            _fixtures._SCOPE_P1,
            account_currency="OFFLINE_TEST_CURRENCY",
            environment="demo",
        ),
    )
    operands = (
        DerivFinancialOperand(
            "offline:operand:stake",
            "offline:semantic:synthetic-stake",
            DerivFinancialUnit.STAKE_CURRENCY_AMOUNT,
            DerivOperandRole.BASE,
            0,
            True,
            DerivNumericDomain.POSITIVE,
            Decimal("0.01"),
            Decimal("1000"),
            False,
            True,
            False,
        ),
        DerivFinancialOperand(
            "offline:operand:factor",
            "offline:semantic:synthetic-factor",
            DerivFinancialUnit.RATIO,
            DerivOperandRole.FACTOR,
            1,
            True,
            DerivNumericDomain.POSITIVE,
            Decimal("0.0001"),
            Decimal("10"),
            False,
            False,
            True,
        ),
    )
    values = {
        "schema_version": 1,
        "semantic_id": "offline:test-fixture:loss-model",
        "semantic_version": 1,
        "equation_family": DerivEquationFamily.SYNTHETIC_LINEAR_PRODUCT,
        "equation_identity_hash": "sha256:" + "a" * 64,
        "operands": operands,
        "output": DerivFinancialOutput(
            DerivOutputSemantic.SYNTHETIC_MONETARY_LOSS_FOR_SUPPLIED_INPUTS,
            DerivFinancialUnit.ACCOUNT_CURRENCY_AMOUNT,
            DerivCurrencyBinding.APPLICABILITY_ACCOUNT_CURRENCY,
            None,
            False,
            True,
        ),
        "rounding": DerivRoundingPolicy(
            True, 2, DerivRoundingMode.ROUND_HALF_EVEN, DerivRoundingStage.FINAL_OUTPUT
        ),
        "domain_constraint_ids": (
            "offline:domain:finite-inputs",
            "offline:domain:synthetic-only",
        ),
        "applicability": scope,
        "contract_family": scope.contract_family,
        "quantity_basis_semantic_id": scope.quantity_basis,
        "stop_semantic_id": scope.stop_loss_semantic_id,
        "multiplier_semantic_id": scope.multiplier_semantics_id,
    }
    values.update(changes)
    return DerivFinancialSemanticsSpecification(**values)


def _chain(semantics=None, *, verification_semantics=..., candidate_id=None):
    semantics = semantics or _semantics()
    artifact = _fixtures._artifact()
    claim = replace(
        artifact.claims[0],
        value=semantics.material_hash,
        applicability=semantics.applicability,
    )
    artifact = replace(artifact, claims=(claim,))
    _, decision, assessment = _fixtures._advisory_chain()
    decision = replace(
        decision,
        applicability=semantics.applicability,
        financial_semantics=semantics,
    )
    assessment = replace(
        assessment,
        applicability=semantics.applicability,
        financial_semantics=semantics,
    )
    candidate = _fixtures._candidate(
        candidate_id=candidate_id or _fixtures._CANDIDATE_ID,
        candidate_material_hash=semantics.material_hash,
        applicability=semantics.applicability,
        financial_semantics=semantics,
    )
    verified_semantics = semantics if verification_semantics is ... else verification_semantics
    verification = _fixtures._verification(
        candidate_id=_fixtures._CANDIDATE_ID,
        candidate_material_hash=verified_semantics.material_hash,
        applicability=verified_semantics.applicability,
        financial_semantics=verified_semantics,
    )
    evidence = DerivEvidenceRegistry().register(artifact)
    eligibility = validate_deriv_proof_registration_eligibility(
        candidate, verification, assessment, decision, evidence
    )
    return eligibility, candidate, verification, assessment, decision, evidence


def test_synthetic_semantics_propagate_through_registry_and_consumption() -> None:
    semantics = _semantics()
    bundle = _chain(semantics)
    eligibility, candidate, verification, assessment, decision, evidence = bundle
    assert eligibility.eligible
    request = replace(
        _fixtures._admission_request(),
        candidate_material_hash=semantics.material_hash,
        applicability=semantics.applicability,
        financial_semantics=semantics,
    )
    admitted = admit_deriv_proof_registry_entry(
        _fixtures.DerivProofRegistryState(),
        request,
        eligibility,
        candidate,
        verification,
        assessment,
        decision,
        evidence,
    )
    entry = admitted.registry.entries[0]
    assert entry.financial_semantics == semantics
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
        evaluated_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        financial_semantics=semantics,
    )
    consumed = validate_authoritative_proof_for_capability(
        admitted.registry, consumption_request
    )
    assert consumed.state is DerivProofConsumptionState.PROOF_AVAILABLE


def _tampered_variants(base):
    first, second = base.operands
    changed_scope = lambda **kwargs: replace(base.applicability, **kwargs)
    return (
        replace(base, equation_identity_hash="sha256:" + "b" * 64),
        replace(base, operands=(replace(first, semantic_id="offline:changed"), second)),
        replace(base, operands=(replace(second, position=0), replace(first, position=1))),
        replace(base, operands=(replace(first, unit=DerivFinancialUnit.PRICE), second)),
        replace(base, output=replace(base.output, unit=DerivFinancialUnit.STAKE_CURRENCY_AMOUNT)),
        replace(base, output=replace(base.output, semantic=DerivOutputSemantic.SYNTHETIC_MAXIMUM_MONETARY_LOSS)),
        replace(base, output=replace(base.output, currency_binding=DerivCurrencyBinding.EXPLICIT_CURRENCY, explicit_currency="OFFLINE_OTHER")),
        replace(base, rounding=replace(base.rounding, precision=3)),
        replace(base, rounding=replace(base.rounding, mode=DerivRoundingMode.ROUND_FLOOR)),
        replace(base, domain_constraint_ids=("offline:domain:changed",)),
        replace(base, applicability=changed_scope(quantity_basis="other"), quantity_basis_semantic_id="other"),
        replace(base, applicability=changed_scope(stop_loss_semantic_id="other"), stop_semantic_id="other"),
        replace(base, applicability=changed_scope(multiplier_semantics_id="other"), multiplier_semantic_id="other"),
        replace(base, applicability=changed_scope(contract_family="OTHER"), contract_family="OTHER"),
        replace(base, applicability=changed_scope(symbol="OTHER")),
        replace(base, applicability=changed_scope(environment="real")),
    )


def test_take_profit_output_is_distinct_monetary_profit_semantics() -> None:
    semantics = _semantics(
        take_profit_output=DerivFinancialOutput(
            DerivOutputSemantic.SYNTHETIC_MONETARY_PROFIT_FOR_SUPPLIED_INPUTS,
            DerivFinancialUnit.ACCOUNT_CURRENCY_AMOUNT,
            DerivCurrencyBinding.APPLICABILITY_ACCOUNT_CURRENCY,
            None,
            False,
            True,
        ),
        take_profit_semantic_id="offline:test-fixture:take-profit-v1",
    )
    assert semantics.output.semantic is DerivOutputSemantic.SYNTHETIC_MONETARY_LOSS_FOR_SUPPLIED_INPUTS
    assert semantics.take_profit_output is not None
    assert semantics.take_profit_output.semantic is DerivOutputSemantic.SYNTHETIC_MONETARY_PROFIT_FOR_SUPPLIED_INPUTS


def test_allowed_multipliers_require_ordered_positive_decimals() -> None:
    semantics = _semantics(allowed_multiplier_values=(Decimal("7"), Decimal("11")))
    assert semantics.allowed_multiplier_values == (Decimal("7"), Decimal("11"))
    for values in (
        (Decimal("0"),),
        (Decimal("NaN"),),
        (Decimal("11"), Decimal("7")),
        (Decimal("7"), Decimal("7")),
        (7,),
    ):
        with pytest.raises(ValueError, match="multiplier"):
            _semantics(allowed_multiplier_values=values)


def test_take_profit_and_multiplier_authority_change_material_identity() -> None:
    base = _semantics()
    with_multiplier = replace(base, allowed_multiplier_values=(Decimal("7"),))
    with_take_profit = replace(
        base,
        take_profit_output=DerivFinancialOutput(
            DerivOutputSemantic.SYNTHETIC_MONETARY_PROFIT_FOR_SUPPLIED_INPUTS,
            DerivFinancialUnit.ACCOUNT_CURRENCY_AMOUNT,
            DerivCurrencyBinding.APPLICABILITY_ACCOUNT_CURRENCY,
            None,
            False,
            True,
        ),
        take_profit_semantic_id="offline:test-fixture:take-profit-v1",
    )
    with_maximum_loss = replace(
        base,
        maximum_loss_output=DerivFinancialOutput(
            DerivOutputSemantic.SYNTHETIC_MAXIMUM_MONETARY_LOSS,
            DerivFinancialUnit.ACCOUNT_CURRENCY_AMOUNT,
            DerivCurrencyBinding.APPLICABILITY_ACCOUNT_CURRENCY,
            None,
            False,
            True,
        ),
        maximum_loss_semantic_id="offline:test-fixture:maximum-loss-v1",
    )
    assert with_multiplier.material_hash != base.material_hash
    assert with_take_profit.material_hash != base.material_hash
    assert with_maximum_loss.material_hash != base.material_hash


@pytest.mark.parametrize("index", range(16))
def test_each_financial_semantic_tamper_changes_canonical_identity(index) -> None:
    base = _semantics()
    changed = _tampered_variants(base)[index]
    assert changed.material_hash != base.material_hash


@pytest.mark.parametrize("index", range(16))
def test_s1_verification_cannot_authorize_s2_candidate(index) -> None:
    s1 = _semantics()
    s2 = _tampered_variants(s1)[index]
    eligibility, *_ = _chain(s2, verification_semantics=s1)
    assert not eligibility.eligible
    assert (
        DerivProofRegistrationReason.INDEPENDENT_VERIFICATION_MISMATCH
        in eligibility.reason_codes
    )


def test_candidate_identity_cannot_be_inherited() -> None:
    eligibility, *_ = _chain(_semantics(), candidate_id="offline:candidate:C2")
    assert not eligibility.eligible
    assert DerivProofRegistrationReason.INDEPENDENT_VERIFICATION_MISMATCH in eligibility.reason_codes


def test_models_are_immutable_and_malformed_semantics_fail_closed() -> None:
    semantics = _semantics()
    with pytest.raises(FrozenInstanceError):
        semantics.semantic_id = "changed"
    with pytest.raises(ValueError, match="duplicate operand"):
        replace(semantics, operands=(semantics.operands[0], semantics.operands[0]))
    with pytest.raises(ValueError, match="rounding"):
        DerivRoundingPolicy(True, None, DerivRoundingMode.NONE, DerivRoundingStage.NONE)


def test_semantics_module_contains_no_equation_execution_or_authority_leakage() -> None:
    source = Path("broker/deriv_financial_semantics.py").read_text(encoding="utf-8")
    forbidden = (
        "eval(", "exec(", "__import__(", "importlib", "submit_order", "OrderRequest",
        "ExecutionIntent", "position_sizing", "authorize_execution_quantity",
        "websockets", "requests.", "os.environ",
    )
    assert all(token not in source for token in forbidden)
