"""Offline tests for typed Deriv contract and exit semantics."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from broker.deriv_contract_semantics import (
    CapabilityState, ContractLifecycleState, DerivContractSemantics,
    DerivProposalRequest, MaximumLossBasis, QuantityBasis,
    SemanticsVerification, build_sell_request, parse_open_contract,
    parse_proposal, parse_purchase, parse_sell, reconcile_contract,
)


def semantics(**changes):
    values = dict(
        canonical_symbol="XAUUSD", provider_symbol="frxXAUUSD",
        contract_type="MULTUP", quantity_basis=QuantityBasis.STAKE,
        multiplier=Decimal("100"), minimum_quantity=Decimal("1.00"),
        maximum_quantity=Decimal("1000.00"), currency="USD",
        duration_semantics=None, barrier_semantics=None,
        stop_loss=CapabilityState.SUPPORTED,
        take_profit=CapabilityState.SUPPORTED, sell=CapabilityState.SUPPORTED,
        proposal_requirements=frozenset({"amount", "basis", "contract_type", "currency", "underlying_symbol", "multiplier"}),
        purchase_identifiers=frozenset({"transaction_id", "contract_id"}),
        open_contract_identifiers=frozenset({"contract_id"}),
        exit_identifiers=frozenset({"contract_id", "transaction_id", "reference_id"}),
        maximum_loss_basis=MaximumLossBasis.BROKER_STOP_LOSS_AMOUNT,
        verified_at=datetime.now(timezone.utc), evidence_source="deriv-demo-proposal",
        evidence_digest="sha256:" + "a" * 64,
        verification_state=SemanticsVerification.VERIFIED,
    )
    values.update(changes)
    return DerivContractSemantics(**values)


def proposal_request():
    return DerivProposalRequest("frxXAUUSD", "MULTUP", Decimal("10.25"), QuantityBasis.STAKE, "USD", multiplier=Decimal("100"))


def proposal_response():
    return {"proposal": {"id": "P1", "ask_price": "10.25", "payout": "20.50", "spot": "2450.125"}, "echo_req": proposal_request().to_payload()}


def purchase_response():
    return {"buy": {"transaction_id": 91, "contract_id": 81, "buy_price": "10.25", "payout": "20.50", "purchase_time": 1700000000, "start_time": 1700000001}, "echo_req": {"buy": "P1", "price": "10.25"}}


def open_response(**changes):
    item = {"contract_id": 81, "contract_type": "MULTUP", "currency": "USD", "buy_price": "10.25", "bid_price": "9.50", "profit": "-0.75", "is_sold": 0, "is_expired": 0, "is_valid_to_sell": 1}
    item.update(changes)
    return {"proposal_open_contract": item}


def sell_response(**changes):
    item = {"contract_id": 81, "transaction_id": 92, "reference_id": 91, "sold_for": "11.35", "balance_after": "100.10"}
    item.update(changes)
    return {"sell": item}


def test_verified_metadata_is_typed_without_granting_submission_authority():
    item = semantics()
    assert item.authoritative_loss_model_available
    assert not hasattr(item, "submission_ready")
    assert isinstance(item.multiplier, Decimal)


@pytest.mark.parametrize("changes", [{"provider_symbol": ""}, {"evidence_source": ""}, {"minimum_quantity": Decimal("0")}])
def test_missing_or_invalid_metadata_fails_closed(changes):
    with pytest.raises(ValueError):
        semantics(**changes)


def test_unsupported_contract_is_explicit_not_ready():
    item = semantics(sell=CapabilityState.UNSUPPORTED)
    assert item.sell is CapabilityState.UNSUPPORTED


def test_quantity_min_max_and_decimal_precision():
    item = semantics()
    item.validate_quantity(Decimal("1.0000000000000000001"))
    with pytest.raises(ValueError):
        item.validate_quantity(Decimal("0.99"))
    with pytest.raises(ValueError):
        item.validate_quantity(Decimal("1000.01"))


def test_verified_maximum_loss_uses_explicit_broker_stop_amount():
    assert semantics().authoritative_maximum_loss(quantity=Decimal("10"), broker_stop_loss_amount=Decimal("2.75")) == Decimal("2.75")


@pytest.mark.parametrize("changes", [{"verification_state": SemanticsVerification.PARTIALLY_VERIFIED}, {"maximum_loss_basis": MaximumLossBasis.UNKNOWN}])
def test_unverified_loss_model_fails_closed(changes):
    with pytest.raises(ValueError):
        semantics(**changes).authoritative_maximum_loss(quantity=Decimal("10"), broker_stop_loss_amount=Decimal("2"))


def test_stake_loss_basis_is_deterministic():
    item = semantics(maximum_loss_basis=MaximumLossBasis.STAKE)
    assert item.authoritative_maximum_loss(quantity=Decimal("10.123")) == Decimal("10.123")


def test_proposal_payload_and_decimal_parsing():
    request = proposal_request()
    assert request.to_payload()["underlying_symbol"] == "frxXAUUSD"
    quote = parse_proposal(proposal_response(), request)
    assert quote.proposal_id == "P1" and quote.ask_price == Decimal("10.25")


@pytest.mark.parametrize("key,value", [("contract_type", "MULTDOWN"), ("underlying_symbol", "R_100"), ("amount", "11")])
def test_proposal_mismatch_rejected(key, value):
    response = proposal_response()
    response["echo_req"][key] = value
    with pytest.raises(ValueError):
        parse_proposal(response, proposal_request())


def test_purchase_binds_proposal_contract_and_transaction():
    receipt = parse_purchase(purchase_response(), proposal_id="P1", request=proposal_request())
    assert receipt.contract_id == "81" and receipt.transaction_id == "91"
    assert receipt.provider_symbol == "frxXAUUSD"
    assert receipt.contract_type == "MULTUP"
    assert receipt.quantity == Decimal("10.25")


def test_purchase_proposal_mismatch_rejected():
    with pytest.raises(ValueError):
        parse_purchase(purchase_response(), proposal_id="OTHER", request=proposal_request())


def test_open_contract_sellability_and_decimal_profit():
    item = parse_open_contract(open_response(), contract_id="81")
    assert item.lifecycle_state is ContractLifecycleState.SELLABLE
    assert item.profit == Decimal("-0.75")


@pytest.mark.parametrize("changes,state", [({"is_sold": 1, "is_valid_to_sell": 0}, ContractLifecycleState.CLOSED), ({"is_expired": 1, "is_valid_to_sell": 0}, ContractLifecycleState.EXPIRED), ({"is_valid_to_sell": 0}, ContractLifecycleState.PURCHASED_OPEN)])
def test_open_contract_lifecycle_states(changes, state):
    assert parse_open_contract(open_response(**changes), contract_id="81").lifecycle_state is state


def test_open_contract_mismatch_rejected():
    with pytest.raises(ValueError):
        parse_open_contract(open_response(), contract_id="82")


def test_sell_request_is_contract_specific_and_nonnegative():
    assert build_sell_request("81") == {"sell": "81", "price": "0"}
    with pytest.raises(ValueError):
        build_sell_request("81", minimum_price=Decimal("-1"))


def test_sell_response_parses_authoritative_identifiers():
    receipt = parse_sell(sell_response(), contract_id="81")
    assert receipt.transaction_id == "92" and receipt.reference_id == "91"


def test_sell_response_contract_mismatch_rejected():
    with pytest.raises(ValueError):
        parse_sell(sell_response(), contract_id="82")


def test_reconciliation_binds_purchase_open_and_realized_profit():
    purchase = parse_purchase(purchase_response(), proposal_id="P1", request=proposal_request())
    opened = parse_open_contract(open_response(), contract_id="81")
    assert reconcile_contract(purchase, opened).state is ContractLifecycleState.SELLABLE
    sold = parse_sell(sell_response(), contract_id="81")
    result = reconcile_contract(purchase, opened, sold)
    assert result.state is ContractLifecycleState.CLOSED
    assert result.realized_profit == Decimal("1.10")


def test_reconciliation_unknown_and_unavailable_fail_closed():
    assert reconcile_contract(None, None).state is ContractLifecycleState.SUBMISSION_UNKNOWN
    purchase = parse_purchase(purchase_response(), proposal_id="P1", request=proposal_request())
    assert reconcile_contract(purchase, None).state is ContractLifecycleState.BROKER_STATE_UNAVAILABLE


def test_capabilities_represent_unsupported_native_limits():
    item = semantics(stop_loss=CapabilityState.UNSUPPORTED, take_profit=CapabilityState.UNSUPPORTED)
    assert item.stop_loss is CapabilityState.UNSUPPORTED
    assert item.take_profit is CapabilityState.UNSUPPORTED
