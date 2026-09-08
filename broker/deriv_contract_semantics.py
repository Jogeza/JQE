"""Typed, fail-closed Deriv contract and lifecycle semantics.

The types in this module parse factual broker observations.  They never grant
execution authority and perform no network or broker mutation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Mapping


class SemanticsVerification(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    PARTIALLY_VERIFIED = "PARTIALLY_VERIFIED"
    VERIFIED = "VERIFIED"


class CapabilityState(str, Enum):
    UNKNOWN = "UNKNOWN"
    UNSUPPORTED = "UNSUPPORTED"
    SUPPORTED = "SUPPORTED"


class QuantityBasis(str, Enum):
    STAKE = "stake"
    PAYOUT = "payout"


class MaximumLossBasis(str, Enum):
    UNKNOWN = "UNKNOWN"
    STAKE = "STAKE"
    BROKER_STOP_LOSS_AMOUNT = "BROKER_STOP_LOSS_AMOUNT"


class ContractLifecycleState(str, Enum):
    SUBMISSION_UNKNOWN = "SUBMISSION_UNKNOWN"
    PURCHASED_OPEN = "PURCHASED_OPEN"
    SELLABLE = "SELLABLE"
    CLOSE_REQUESTED = "CLOSE_REQUESTED"
    CLOSED = "CLOSED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    RECONCILIATION_MISMATCH = "RECONCILIATION_MISMATCH"
    BROKER_STATE_UNAVAILABLE = "BROKER_STATE_UNAVAILABLE"


def _text(value: Any, name: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{name} must be a nonblank string")
    return value.strip()


def _identifier(value: Any, name: str) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError(f"{name} is missing or invalid")
    result = str(value).strip()
    if not result:
        raise ValueError(f"{name} is missing or invalid")
    return result


def _decimal(value: Any, name: str, *, positive: bool = False) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{name} is missing or invalid")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{name} is missing or invalid") from exc
    if not result.is_finite() or (positive and result <= 0):
        raise ValueError(f"{name} is missing or invalid")
    return result


def _optional_decimal(value: Any, name: str) -> Decimal | None:
    return None if value is None else _decimal(value, name)


def _epoch(value: Any, name: str) -> datetime:
    if isinstance(value, bool):
        raise ValueError(f"{name} is missing or invalid")
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except (TypeError, ValueError, OSError) as exc:
        raise ValueError(f"{name} is missing or invalid") from exc


@dataclass(frozen=True, slots=True)
class DerivContractSemantics:
    canonical_symbol: str
    provider_symbol: str
    contract_type: str
    quantity_basis: QuantityBasis
    multiplier: Decimal | None
    minimum_quantity: Decimal
    maximum_quantity: Decimal | None
    currency: str
    duration_semantics: str | None
    barrier_semantics: str | None
    stop_loss: CapabilityState
    take_profit: CapabilityState
    sell: CapabilityState
    proposal_requirements: frozenset[str]
    purchase_identifiers: frozenset[str]
    open_contract_identifiers: frozenset[str]
    exit_identifiers: frozenset[str]
    maximum_loss_basis: MaximumLossBasis
    verified_at: datetime
    evidence_source: str
    evidence_digest: str
    verification_state: SemanticsVerification

    def __post_init__(self) -> None:
        for name in ("canonical_symbol", "provider_symbol", "contract_type", "currency", "evidence_source", "evidence_digest"):
            _text(getattr(self, name), name)
        if type(self.minimum_quantity) is not Decimal or self.minimum_quantity <= 0:
            raise ValueError("minimum_quantity must be a positive Decimal")
        if self.maximum_quantity is not None and (
            type(self.maximum_quantity) is not Decimal
            or self.maximum_quantity < self.minimum_quantity
        ):
            raise ValueError("maximum_quantity must be a Decimal at or above minimum")
        if self.multiplier is not None and (type(self.multiplier) is not Decimal or self.multiplier <= 0):
            raise ValueError("multiplier must be a positive Decimal")
        if self.verified_at.tzinfo is None:
            raise ValueError("verified_at must be timezone-aware")
        for name in ("proposal_requirements", "purchase_identifiers", "open_contract_identifiers", "exit_identifiers"):
            value = getattr(self, name)
            if not isinstance(value, frozenset) or any(type(item) is not str or not item for item in value):
                raise ValueError(f"{name} must be an immutable nonblank set")

    def validate_quantity(self, quantity: Decimal) -> None:
        if type(quantity) is not Decimal or not quantity.is_finite() or quantity < self.minimum_quantity:
            raise ValueError("quantity is below the verified minimum or invalid")
        if self.maximum_quantity is not None and quantity > self.maximum_quantity:
            raise ValueError("quantity exceeds the verified maximum")

    def authoritative_maximum_loss(
        self, *, quantity: Decimal, broker_stop_loss_amount: Decimal | None = None
    ) -> Decimal:
        if self.verification_state is not SemanticsVerification.VERIFIED:
            raise ValueError("contract semantics are not fully verified")
        self.validate_quantity(quantity)
        if self.maximum_loss_basis is MaximumLossBasis.STAKE:
            return quantity
        if self.maximum_loss_basis is MaximumLossBasis.BROKER_STOP_LOSS_AMOUNT:
            if type(broker_stop_loss_amount) is not Decimal or broker_stop_loss_amount <= 0:
                raise ValueError("verified broker stop-loss amount is required")
            if broker_stop_loss_amount > quantity:
                raise ValueError("stop-loss amount cannot exceed stake")
            return broker_stop_loss_amount
        raise ValueError("maximum-loss basis is unverified")

    @property
    def authoritative_loss_model_available(self) -> bool:
        """Report model completeness only; never submission authority."""
        return (
            self.verification_state is SemanticsVerification.VERIFIED
            and self.maximum_loss_basis is not MaximumLossBasis.UNKNOWN
        )


@dataclass(frozen=True, slots=True)
class DerivProposalRequest:
    provider_symbol: str
    contract_type: str
    amount: Decimal
    basis: QuantityBasis
    currency: str
    multiplier: Decimal | None = None
    duration: int | None = None
    duration_unit: str | None = None
    limit_order: Mapping[str, Decimal] | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "proposal": 1,
            "amount": str(self.amount),
            "basis": self.basis.value,
            "contract_type": _text(self.contract_type, "contract_type"),
            "currency": _text(self.currency, "currency"),
            "underlying_symbol": _text(self.provider_symbol, "provider_symbol"),
        }
        if self.amount <= 0:
            raise ValueError("amount must be positive")
        if self.multiplier is not None:
            if self.multiplier <= 0:
                raise ValueError("multiplier must be positive")
            payload["multiplier"] = str(self.multiplier)
        if (self.duration is None) != (self.duration_unit is None):
            raise ValueError("duration and duration_unit must be supplied together")
        if self.duration is not None:
            if type(self.duration) is not int or self.duration <= 0:
                raise ValueError("duration must be a positive integer")
            payload.update(duration=self.duration, duration_unit=_text(self.duration_unit, "duration_unit"))
        if self.limit_order is not None:
            payload["limit_order"] = {key: str(value) for key, value in self.limit_order.items()}
        return payload


@dataclass(frozen=True, slots=True)
class DerivProposalQuote:
    proposal_id: str
    ask_price: Decimal
    payout: Decimal | None
    spot: Decimal | None


def parse_proposal(response: Mapping[str, Any], request: DerivProposalRequest) -> DerivProposalQuote:
    proposal = response.get("proposal")
    echo = response.get("echo_req")
    if not isinstance(proposal, Mapping) or not isinstance(echo, Mapping):
        raise ValueError("proposal response lacks factual proposal or echo")
    expected = request.to_payload()
    for key in ("contract_type", "currency", "underlying_symbol", "basis"):
        if echo.get(key) != expected[key]:
            raise ValueError(f"proposal {key} mismatch")
    if _decimal(echo.get("amount"), "echo amount", positive=True) != request.amount:
        raise ValueError("proposal amount mismatch")
    for key in ("multiplier", "duration", "duration_unit", "limit_order"):
        if key in expected and echo.get(key) != expected[key]:
            raise ValueError(f"proposal {key} mismatch")
    return DerivProposalQuote(
        _identifier(proposal.get("id"), "proposal id"),
        _decimal(proposal.get("ask_price"), "ask_price", positive=True),
        _optional_decimal(proposal.get("payout"), "payout"),
        _optional_decimal(proposal.get("spot"), "spot"),
    )


@dataclass(frozen=True, slots=True)
class DerivPurchaseReceipt:
    proposal_id: str
    provider_symbol: str
    contract_type: str
    quantity: Decimal
    quantity_basis: QuantityBasis
    transaction_id: str
    contract_id: str
    buy_price: Decimal
    payout: Decimal | None
    purchase_time: datetime
    start_time: datetime


def parse_purchase(
    response: Mapping[str, Any], *, proposal_id: str, request: DerivProposalRequest
) -> DerivPurchaseReceipt:
    buy = response.get("buy")
    echo = response.get("echo_req")
    if not isinstance(buy, Mapping) or not isinstance(echo, Mapping) or str(echo.get("buy")) != proposal_id:
        raise ValueError("purchase response does not bind the proposal")
    return DerivPurchaseReceipt(
        proposal_id,
        request.provider_symbol,
        request.contract_type,
        request.amount,
        request.basis,
        _identifier(buy.get("transaction_id"), "transaction_id"),
        _identifier(buy.get("contract_id"), "contract_id"),
        _decimal(buy.get("buy_price"), "buy_price", positive=True),
        _optional_decimal(buy.get("payout"), "payout"),
        _epoch(buy.get("purchase_time"), "purchase_time"),
        _epoch(buy.get("start_time"), "start_time"),
    )


@dataclass(frozen=True, slots=True)
class DerivOpenContract:
    contract_id: str
    contract_type: str
    currency: str
    buy_price: Decimal
    bid_price: Decimal | None
    profit: Decimal | None
    is_sold: bool
    is_expired: bool
    is_valid_to_sell: bool

    @property
    def lifecycle_state(self) -> ContractLifecycleState:
        if self.is_sold:
            return ContractLifecycleState.CLOSED
        if self.is_expired:
            return ContractLifecycleState.EXPIRED
        if self.is_valid_to_sell:
            return ContractLifecycleState.SELLABLE
        return ContractLifecycleState.PURCHASED_OPEN


def parse_open_contract(response: Mapping[str, Any], *, contract_id: str) -> DerivOpenContract:
    item = response.get("proposal_open_contract")
    if not isinstance(item, Mapping) or _identifier(item.get("contract_id"), "contract_id") != contract_id:
        raise ValueError("open-contract identifier mismatch")
    for flag in ("is_sold", "is_expired", "is_valid_to_sell"):
        if item.get(flag) not in (0, 1, False, True):
            raise ValueError(f"{flag} is missing or invalid")
    return DerivOpenContract(
        contract_id,
        _text(item.get("contract_type"), "contract_type"),
        _text(item.get("currency"), "currency"),
        _decimal(item.get("buy_price"), "buy_price", positive=True),
        _optional_decimal(item.get("bid_price"), "bid_price"),
        _optional_decimal(item.get("profit"), "profit"),
        bool(item.get("is_sold")),
        bool(item.get("is_expired")),
        bool(item.get("is_valid_to_sell")),
    )


@dataclass(frozen=True, slots=True)
class DerivSellReceipt:
    contract_id: str
    transaction_id: str
    reference_id: str
    sold_for: Decimal
    balance_after: Decimal


def build_sell_request(contract_id: str, *, minimum_price: Decimal = Decimal("0")) -> dict[str, Any]:
    if type(minimum_price) is not Decimal or not minimum_price.is_finite() or minimum_price < 0:
        raise ValueError("minimum sell price must be a nonnegative Decimal")
    return {"sell": _identifier(contract_id, "contract_id"), "price": str(minimum_price)}


def parse_sell(response: Mapping[str, Any], *, contract_id: str) -> DerivSellReceipt:
    item = response.get("sell")
    if not isinstance(item, Mapping) or _identifier(item.get("contract_id"), "contract_id") != contract_id:
        raise ValueError("sell response contract mismatch")
    return DerivSellReceipt(
        contract_id,
        _identifier(item.get("transaction_id"), "transaction_id"),
        _identifier(item.get("reference_id"), "reference_id"),
        _decimal(item.get("sold_for"), "sold_for"),
        _decimal(item.get("balance_after"), "balance_after"),
    )


@dataclass(frozen=True, slots=True)
class DerivContractReconciliation:
    state: ContractLifecycleState
    contract_id: str | None
    transaction_id: str | None
    realized_profit: Decimal | None
    reason: str


def reconcile_contract(
    purchase: DerivPurchaseReceipt | None,
    observation: DerivOpenContract | None,
    sale: DerivSellReceipt | None = None,
) -> DerivContractReconciliation:
    if purchase is None:
        return DerivContractReconciliation(ContractLifecycleState.SUBMISSION_UNKNOWN, None, None, None, "purchase identity unavailable")
    if observation is None:
        return DerivContractReconciliation(ContractLifecycleState.BROKER_STATE_UNAVAILABLE, purchase.contract_id, purchase.transaction_id, None, "broker contract state unavailable")
    if observation.contract_id != purchase.contract_id or (sale is not None and sale.contract_id != purchase.contract_id):
        return DerivContractReconciliation(ContractLifecycleState.RECONCILIATION_MISMATCH, purchase.contract_id, purchase.transaction_id, None, "contract identifiers conflict")
    if sale is not None:
        return DerivContractReconciliation(ContractLifecycleState.CLOSED, purchase.contract_id, sale.transaction_id, sale.sold_for - purchase.buy_price, "sell receipt reconciled")
    return DerivContractReconciliation(observation.lifecycle_state, purchase.contract_id, purchase.transaction_id, observation.profit if observation.is_sold else None, "open-contract observation reconciled")
