"""Mocked-first tests for bounded DEMO read/proposal discovery."""

from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from broker.deriv_demo_proposal import (
    discover_demo_proposal, parse_active_symbol, parse_contract_capability,
)


SYMBOLS = {"active_symbols": [{"underlying_symbol": "frxXAUUSD", "underlying_symbol_name": "Gold/USD", "market": "forex", "submarket": "commodities", "exchange_is_open": 1}]}
CONTRACTS = {"contracts_for": {"available": [{"underlying_symbol": "frxXAUUSD", "contract_type": "MULTUP", "basis": "stake", "multiplier_range": [100, "200"], "minimum_stake": "1.00", "maximum_stake": "1000.00", "duration_units": ["s", "m"], "min_contract_duration": "1s", "max_contract_duration": "365d", "barriers": 0, "limit_order_fields": ["stop_loss", "take_profit"]}]}}


def proposal():
    return {"proposal": {"id": "opaque", "ask_price": "1.00", "payout": "1.50", "spot": "2500.123456789"}, "echo_req": {"proposal": 1, "amount": "1.00", "basis": "stake", "contract_type": "MULTUP", "currency": "USD", "underlying_symbol": "frxXAUUSD", "multiplier": "100"}}


def test_symbol_and_contract_metadata_parsing():
    symbol = parse_active_symbol(SYMBOLS, "frxXAUUSD")
    assert symbol.display_name == "Gold/USD" and symbol.is_open
    capability = parse_contract_capability(CONTRACTS, provider_symbol="frxXAUUSD", contract_type="MULTUP")
    assert capability.multiplier_values == (Decimal("100"), Decimal("200"))
    assert capability.minimum_quantity == Decimal("1.00")
    assert capability.maximum_quantity == Decimal("1000.00")
    assert capability.duration_units == ("m", "s") and capability.barriers == 0
    assert capability.stop_loss_advertised and capability.take_profit_advertised


def test_symbol_mismatch_and_live_contract_absence_fail_closed():
    with pytest.raises(ValueError):
        parse_active_symbol(SYMBOLS, "R_100")
    with pytest.raises(ValueError):
        parse_contract_capability(CONTRACTS, provider_symbol="frxXAUUSD", contract_type="MULTDOWN")


@pytest.mark.parametrize("field,value", [("minimum_stake", "nan"), ("maximum_stake", "0"), ("barriers", "zero")])
def test_malformed_contract_metadata_rejected(field, value):
    response = {"contracts_for": {"available": [dict(CONTRACTS["contracts_for"]["available"][0], **{field: value})]}}
    with pytest.raises(ValueError):
        parse_contract_capability(response, provider_symbol="frxXAUUSD", contract_type="MULTUP")


@pytest.mark.asyncio
async def test_discovery_uses_minimum_stake_and_validates_proposal():
    transport = AsyncMock()
    transport.request.side_effect = [SYMBOLS, CONTRACTS, proposal()]
    result = await discover_demo_proposal(transport, provider_symbol="frxXAUUSD", currency="USD")
    assert result.proposal_verified
    assert result.spot == Decimal("2500.123456789")
    sent = transport.request.await_args_list[2].args[0]
    assert sent["amount"] == "1.00" and sent["multiplier"] == "100"


@pytest.mark.asyncio
async def test_missing_multiplier_or_minimum_never_requests_proposal():
    item = dict(CONTRACTS["contracts_for"]["available"][0])
    item.pop("multiplier_range")
    transport = AsyncMock()
    transport.request.side_effect = [SYMBOLS, {"contracts_for": {"available": [item]}}]
    with pytest.raises(ValueError, match="multiplier"):
        await discover_demo_proposal(transport, provider_symbol="frxXAUUSD", currency="USD")
    assert transport.request.await_count == 2


def test_semantic_hash_excludes_dynamic_prices_and_is_deterministic():
    first = parse_contract_capability(CONTRACTS, provider_symbol="frxXAUUSD", contract_type="MULTUP")
    second = parse_contract_capability(CONTRACTS, provider_symbol="frxXAUUSD", contract_type="MULTUP")
    assert first.semantic_hash == second.semantic_hash
