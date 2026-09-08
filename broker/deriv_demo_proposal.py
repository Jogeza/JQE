"""DEMO-only read/proposal evidence discovery with no purchase capability."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Protocol

from broker.deriv_contract_semantics import DerivProposalRequest, QuantityBasis, parse_proposal


class ReadProposalTransport(Protocol):
    async def request(self, payload: Mapping[str, Any]) -> Mapping[str, Any]: ...


def _decimal(value: Any, name: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{name} is missing")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{name} is invalid") from exc
    if not result.is_finite() or result <= 0:
        raise ValueError(f"{name} is invalid")
    return result


def _optional_decimal(item: Mapping[str, Any], names: tuple[str, ...]) -> Decimal | None:
    present = [(name, item[name]) for name in names if item.get(name) is not None]
    if not present:
        return None
    values = {_decimal(value, name) for name, value in present}
    if len(values) != 1:
        raise ValueError("conflicting contract limits")
    return next(iter(values))


def _decimal_values(value: Any) -> tuple[Decimal, ...]:
    if isinstance(value, Mapping):
        value = value.get("values") or value.get("list")
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(sorted({_decimal(item, "multiplier") for item in value}))


@dataclass(frozen=True, slots=True)
class DerivSymbolEvidence:
    provider_symbol: str
    display_name: str | None
    market: str | None
    submarket: str | None
    is_open: bool | None


@dataclass(frozen=True, slots=True)
class DerivContractCapabilityEvidence:
    provider_symbol: str
    contract_type: str
    quantity_basis: QuantityBasis | None
    multiplier_values: tuple[Decimal, ...]
    minimum_quantity: Decimal | None
    maximum_quantity: Decimal | None
    duration_units: tuple[str, ...]
    minimum_duration: str | None
    maximum_duration: str | None
    barriers: int | None
    stop_loss_advertised: bool | None
    take_profit_advertised: bool | None
    sell_advertised: bool | None
    observed_at: datetime
    semantic_hash: str


def parse_active_symbol(response: Mapping[str, Any], provider_symbol: str) -> DerivSymbolEvidence:
    records = response.get("active_symbols")
    if not isinstance(records, list):
        raise ValueError("active-symbol response is malformed")
    matches = [item for item in records if isinstance(item, Mapping) and (item.get("underlying_symbol") or item.get("symbol")) == provider_symbol]
    if len(matches) != 1:
        raise ValueError("provider symbol is missing or ambiguous")
    item = matches[0]
    open_value = item.get("exchange_is_open", item.get("is_trading_suspended"))
    is_open = None if open_value is None else bool(open_value) if "exchange_is_open" in item else not bool(open_value)
    return DerivSymbolEvidence(
        provider_symbol,
        item.get("underlying_symbol_name") or item.get("display_name"),
        item.get("market"),
        item.get("submarket"),
        is_open,
    )


def parse_contract_capability(
    response: Mapping[str, Any], *, provider_symbol: str, contract_type: str
) -> DerivContractCapabilityEvidence:
    container = response.get("contracts_for")
    available = container.get("available") if isinstance(container, Mapping) else None
    if not isinstance(available, list):
        raise ValueError("contract capability response is malformed")
    matches = [item for item in available if isinstance(item, Mapping) and item.get("contract_type") == contract_type and item.get("underlying_symbol") == provider_symbol]
    if len(matches) != 1:
        raise ValueError("contract capability is missing or ambiguous")
    item = matches[0]
    multiplier_values = ()
    for name in ("multiplier_values", "multiplier_range", "multipliers"):
        values = _decimal_values(item.get(name))
        if values:
            if multiplier_values and values != multiplier_values:
                raise ValueError("conflicting multiplier metadata")
            multiplier_values = values
    minimum = _optional_decimal(item, ("minimum_stake", "minimum_contract_amount", "min_contract_amount"))
    maximum = _optional_decimal(item, ("maximum_stake", "maximum_contract_amount", "max_contract_amount"))
    if minimum is not None and maximum is not None and maximum < minimum:
        raise ValueError("conflicting contract limits")
    basis_value = item.get("basis") or item.get("quantity_basis")
    basis = QuantityBasis(basis_value) if basis_value in {value.value for value in QuantityBasis} else None
    duration_units = item.get("duration_units")
    normalized_units = tuple(sorted(str(value) for value in duration_units)) if isinstance(duration_units, list) else ()
    barriers = item.get("barriers")
    if barriers is not None and (isinstance(barriers, bool) or not isinstance(barriers, int) or barriers < 0):
        raise ValueError("barrier metadata is invalid")
    limits = item.get("limit_order") or item.get("limit_order_fields")
    limit_names = set(limits) if isinstance(limits, (list, tuple, set)) else set(limits) if isinstance(limits, Mapping) else set()
    stable = {
        "provider_symbol": provider_symbol, "contract_type": contract_type,
        "quantity_basis": basis.value if basis else None,
        "multiplier_values": [str(value) for value in multiplier_values],
        "minimum_quantity": str(minimum) if minimum else None,
        "maximum_quantity": str(maximum) if maximum else None,
        "duration_units": normalized_units, "minimum_duration": item.get("min_contract_duration"),
        "maximum_duration": item.get("max_contract_duration"), "barriers": barriers,
        "limit_order_fields": sorted(limit_names),
    }
    digest = hashlib.sha256(json.dumps(stable, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return DerivContractCapabilityEvidence(
        provider_symbol, contract_type, basis, multiplier_values, minimum, maximum,
        normalized_units, item.get("min_contract_duration"), item.get("max_contract_duration"),
        barriers, "stop_loss" in limit_names if limit_names else None,
        "take_profit" in limit_names if limit_names else None,
        item.get("is_valid_to_sell") if isinstance(item.get("is_valid_to_sell"), bool) else None,
        datetime.now(timezone.utc), f"sha256:{digest}",
    )


@dataclass(frozen=True, slots=True)
class DemoProposalEvidence:
    symbol: DerivSymbolEvidence
    capability: DerivContractCapabilityEvidence
    proposal_verified: bool
    ask_price: Decimal | None
    payout: Decimal | None
    spot: Decimal | None


async def discover_demo_proposal(
    transport: ReadProposalTransport, *, provider_symbol: str, currency: str,
    contract_type: str = "MULTUP",
) -> DemoProposalEvidence:
    symbol = parse_active_symbol(await transport.request({"active_symbols": "brief"}), provider_symbol)
    capability = parse_contract_capability(
        await transport.request({"contracts_for": provider_symbol}),
        provider_symbol=provider_symbol, contract_type=contract_type,
    )
    if capability.quantity_basis is not QuantityBasis.STAKE:
        raise ValueError("stake quantity basis is not broker-verified")
    if not capability.multiplier_values:
        raise ValueError("multiplier values are not broker-verified")
    if capability.minimum_quantity is None:
        raise ValueError("minimum stake is not broker-verified")
    request = DerivProposalRequest(
        provider_symbol, contract_type, capability.minimum_quantity,
        QuantityBasis.STAKE, currency, multiplier=capability.multiplier_values[0],
    )
    quote = parse_proposal(await transport.request(request.to_payload()), request)
    return DemoProposalEvidence(symbol, capability, True, quote.ask_price, quote.payout, quote.spot)
