"""Broker-neutral observations used during unknown-outcome recovery."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from datetime import datetime
from typing import Protocol

from broker.types import Position, TradeHistoryEntry


class BrokerReconciliationState(str, Enum):
    CONFIRMED_MATCH = "CONFIRMED_MATCH"
    CONFIRMED_ABSENCE = "CONFIRMED_ABSENCE"
    AMBIGUOUS = "AMBIGUOUS"
    UNAVAILABLE = "UNAVAILABLE"


class CorrelationStrength(str, Enum):
    """Strength of evidence linking broker observations to a JQE intent."""

    EXACT = "EXACT"
    AMBIGUOUS = "AMBIGUOUS"
    ABSENT = "ABSENT"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class CorrelationEvidence:
    """Immutable broker evidence; broker IDs are never JQE identity."""

    broker: str
    correlation_strength: CorrelationStrength
    idempotency_key: str | None = None
    order_id: str | None = None
    deal_id: str | None = None
    position_id: str | None = None
    transaction_id: str | None = None
    contract_id: str | None = None
    request_id: str | None = None
    symbol: str | None = None
    side: str | None = None
    volume: float | None = None
    timestamps: tuple[datetime, ...] = ()
    source: str | None = None
    reason: str = ""


@dataclass(frozen=True, slots=True)
class BrokerReconciliationResult:
    state: BrokerReconciliationState
    reason: str
    contract_id: str | None = None
    transaction_id: str | None = None
    evidence: CorrelationEvidence | None = None


class DerivObservationGateway(Protocol):
    async def get_positions(self) -> list[Position]: ...
    async def get_trade_history(self, count: int = 100) -> list[TradeHistoryEntry]: ...


class DerivReconciliationAdapter:
    """Deriv-specific evidence lookup kept outside the generic executor."""

    def __init__(self, gateway: DerivObservationGateway) -> None:
        self._gateway = gateway

    async def reconcile(self, *, order_id: str | None = None, contract_id: str | None = None, transaction_id: str | None = None, symbol: str | None = None, idempotency_key: str | None = None) -> BrokerReconciliationResult:
        contract_id = contract_id or order_id
        try:
            positions = await self._gateway.get_positions()
            history = await self._gateway.get_trade_history()
        except Exception:
            return _result(BrokerReconciliationState.UNAVAILABLE, "Deriv state unavailable", idempotency_key=idempotency_key)
        for item in (*positions, *history):
            item_contract = getattr(item, "position_id", None) or getattr(item, "trade_id", None)
            item_transaction = getattr(item, "transaction_id", None)
            if contract_id is not None and str(item_contract) == str(contract_id):
                return _result(BrokerReconciliationState.CONFIRMED_MATCH, "Contract ID matched", idempotency_key=idempotency_key, contract_id=str(item_contract), transaction_id=str(item_transaction) if item_transaction is not None else None, item=item)
            if transaction_id is not None and item_transaction is not None and str(item_transaction) == str(transaction_id):
                return _result(BrokerReconciliationState.CONFIRMED_MATCH, "Transaction ID matched", idempotency_key=idempotency_key, contract_id=str(item_contract) if item_contract else None, transaction_id=str(item_transaction), item=item)
        symbol_match = bool(symbol) and any(getattr(item, "symbol", "").strip().upper() == symbol.strip().upper() for item in (*positions, *history))
        return classify_observation(broker_available=True, symbol_match=symbol_match, broker="deriv", idempotency_key=idempotency_key)


class MT5ObservationGateway(Protocol):
    async def get_positions(self) -> list[object]: ...
    async def get_trade_history(self, count: int = 100) -> list[object]: ...


class MT5ReconciliationAdapter:
    """Conservative MT5 evidence lookup, isolated from the generic executor."""

    def __init__(self, gateway: MT5ObservationGateway) -> None:
        self._gateway = gateway

    async def reconcile(
        self,
        *,
        order_id: str | None = None,
        deal_id: str | None = None,
        position_id: str | None = None,
        request_id: str | None = None,
        transaction_id: str | None = None,
        symbol: str | None = None,
        idempotency_key: str | None = None,
    ) -> BrokerReconciliationResult:
        try:
            positions = tuple(await self._gateway.get_positions())
            history = tuple(await self._gateway.get_trade_history())
        except Exception:
            return _result(BrokerReconciliationState.UNAVAILABLE, "MT5 state unavailable", broker="mt5", idempotency_key=idempotency_key)
        records = (*positions, *history)
        for item in records:
            if _matches_id(item, order_id, ("order_id", "order")) or _matches_id(item, deal_id, ("deal_id", "deal", "trade_id")) or _matches_id(item, position_id, ("position_id", "position_identifier")) or _matches_id(item, request_id, ("request_id",)):
                return _result(BrokerReconciliationState.CONFIRMED_MATCH, "MT5 broker identifier matched", broker="mt5", idempotency_key=idempotency_key, item=item, order_id=order_id, deal_id=deal_id, position_id=position_id, request_id=request_id)
        evidence_present = bool(records) and any(_has_evidence(item) for item in records)
        if evidence_present or symbol:
            return _result(BrokerReconciliationState.AMBIGUOUS, "MT5 evidence lacks intent correlation", broker="mt5", idempotency_key=idempotency_key, symbol=symbol)
        return _result(BrokerReconciliationState.CONFIRMED_ABSENCE, "MT5 query returned no usable evidence", broker="mt5", idempotency_key=idempotency_key)


def classify_observation(*, broker_available: bool, symbol_match: bool, broker: str = "unknown", idempotency_key: str | None = None) -> BrokerReconciliationResult:
    """Classify evidence without claiming symbol/side correlation."""
    if not broker_available:
        return _result(BrokerReconciliationState.UNAVAILABLE, "Broker state unavailable", broker=broker, idempotency_key=idempotency_key)
    if symbol_match:
        return _result(BrokerReconciliationState.AMBIGUOUS, "Symbol match lacks intent correlation", broker=broker, idempotency_key=idempotency_key)
    return _result(BrokerReconciliationState.AMBIGUOUS, "Broker absence does not prove non-execution", broker=broker, idempotency_key=idempotency_key)


def _matches_id(item: object, expected: str | None, fields: tuple[str, ...]) -> bool:
    if expected is None:
        return False
    expected_value = str(expected)
    return any((value := getattr(item, field, None)) is not None and str(value) == expected_value for field in fields)


def _has_evidence(item: object) -> bool:
    return any(getattr(item, field, None) not in (None, "") for field in ("order_id", "order", "deal_id", "deal", "position_id", "position_identifier", "trade_id", "symbol", "magic", "comment"))


def _result(state: BrokerReconciliationState, reason: str, *, broker: str = "deriv", idempotency_key: str | None = None, item: object | None = None, contract_id: str | None = None, transaction_id: str | None = None, order_id: str | None = None, deal_id: str | None = None, position_id: str | None = None, request_id: str | None = None, symbol: str | None = None) -> BrokerReconciliationResult:
    item_symbol = getattr(item, "symbol", None) if item is not None else None
    item_side = getattr(item, "side", None) if item is not None else None
    item_volume = getattr(item, "volume", None) if item is not None else None
    item_times = tuple(value for value in (getattr(item, "opened_at", None), getattr(item, "closed_at", None)) if isinstance(value, datetime)) if item is not None else ()
    evidence = CorrelationEvidence(
        broker=broker,
        correlation_strength=CorrelationStrength.EXACT if state is BrokerReconciliationState.CONFIRMED_MATCH else CorrelationStrength.UNAVAILABLE if state is BrokerReconciliationState.UNAVAILABLE else CorrelationStrength.ABSENT if state is BrokerReconciliationState.CONFIRMED_ABSENCE else CorrelationStrength.AMBIGUOUS,
        idempotency_key=idempotency_key,
        order_id=order_id,
        deal_id=deal_id,
        position_id=position_id or (str(getattr(item, "position_id", "")) or None if item is not None else None),
        transaction_id=transaction_id,
        contract_id=contract_id,
        request_id=request_id,
        symbol=symbol or item_symbol,
        side=getattr(item_side, "value", item_side),
        volume=float(item_volume) if isinstance(item_volume, (int, float)) and not isinstance(item_volume, bool) else None,
        timestamps=item_times,
        source=type(item).__name__ if item is not None else None,
        reason=reason,
    )
    return BrokerReconciliationResult(state, reason, contract_id, transaction_id, evidence)
