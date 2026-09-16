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
        contract_id = _normalize_identifier(contract_id) or _normalize_identifier(order_id)
        transaction_id = _normalize_identifier(transaction_id)
        try:
            positions = await self._gateway.get_positions()
            history = await self._gateway.get_trade_history()
        except Exception:
            return _result(BrokerReconciliationState.UNAVAILABLE, "Deriv state unavailable", idempotency_key=idempotency_key)
        observations = tuple(
            (
                item,
                _normalize_identifier(item_contract),
                _normalize_identifier(item_transaction),
            )
            for item in (*positions, *history)
            for item_contract, item_transaction in ((
                getattr(item, "position_id", None) or getattr(item, "trade_id", None),
                getattr(item, "transaction_id", None),
            ),)
        )
        contract_matches = tuple(
            observation for observation in observations
            if contract_id is not None and observation[1] == contract_id
        )
        transaction_matches = tuple(
            observation for observation in observations
            if transaction_id is not None and observation[2] == transaction_id
        )

        if contract_id is not None and transaction_id is not None:
            conflicting = any(
                item_transaction is not None and item_transaction != transaction_id
                for _, _, item_transaction in contract_matches
            ) or any(
                item_contract is not None and item_contract != contract_id
                for _, item_contract, _ in transaction_matches
            )
            exact = tuple(
                observation for observation in observations
                if observation[1] == contract_id and observation[2] == transaction_id
            )
            if conflicting or not exact:
                if contract_matches or transaction_matches:
                    return _result(
                        BrokerReconciliationState.AMBIGUOUS,
                        "Deriv authoritative identifiers conflict",
                        idempotency_key=idempotency_key,
                        contract_id=contract_id,
                        transaction_id=transaction_id,
                    )
            else:
                item = exact[0][0]
                return _result(BrokerReconciliationState.CONFIRMED_MATCH, "Contract and transaction IDs matched", idempotency_key=idempotency_key, contract_id=contract_id, transaction_id=transaction_id, item=item)
        elif contract_matches:
            transaction_values = {value for _, _, value in contract_matches if value is not None}
            if len(transaction_values) > 1:
                return _result(BrokerReconciliationState.AMBIGUOUS, "Deriv contract observations conflict", idempotency_key=idempotency_key, contract_id=contract_id)
            item, item_contract, item_transaction = contract_matches[0]
            return _result(BrokerReconciliationState.CONFIRMED_MATCH, "Contract ID matched", idempotency_key=idempotency_key, contract_id=item_contract, transaction_id=item_transaction, item=item)
        elif transaction_matches:
            contract_values = {value for _, value, _ in transaction_matches if value is not None}
            if len(contract_values) > 1:
                return _result(BrokerReconciliationState.AMBIGUOUS, "Deriv transaction observations conflict", idempotency_key=idempotency_key, transaction_id=transaction_id)
            item, item_contract, item_transaction = transaction_matches[0]
            return _result(BrokerReconciliationState.CONFIRMED_MATCH, "Transaction ID matched", idempotency_key=idempotency_key, contract_id=item_contract, transaction_id=item_transaction, item=item)

        symbol_match = bool(symbol) and any(getattr(item, "symbol", "").strip().upper() == symbol.strip().upper() for item, _, _ in observations)
        return classify_observation(broker_available=True, symbol_match=symbol_match, broker="deriv", idempotency_key=idempotency_key)


class MT5ObservationGateway(Protocol):
    async def get_positions(self) -> list[object]: ...
    async def get_trade_history(self, count: int = 100) -> list[object]: ...


class PositionLedger(Protocol):
    def open_entries(self, *, broker: str) -> tuple[object, ...]: ...


class SimulationObservationGateway(Protocol):
    async def get_positions(self) -> list[Position]: ...
    async def get_trade_history(self, count: int = 100) -> list[TradeHistoryEntry]: ...


class SimulationReconciliationAdapter:
    """Recover simulation intents only from exact persisted broker identity."""

    def __init__(self, gateway: SimulationObservationGateway) -> None:
        self._gateway = gateway

    async def reconcile(
        self,
        *,
        order_id: str | None = None,
        transaction_id: str | None = None,
        symbol: str | None = None,
        idempotency_key: str | None = None,
    ) -> BrokerReconciliationResult:
        try:
            positions = tuple(await self._gateway.get_positions())
            history = tuple(await self._gateway.get_trade_history())
        except Exception:
            return _result(
                BrokerReconciliationState.UNAVAILABLE,
                "Simulation state unavailable",
                broker="simulation",
                idempotency_key=idempotency_key,
            )
        for item in (*positions, *history):
            item_order_id = getattr(item, "position_id", None) or getattr(item, "trade_id", None)
            item_transaction_id = getattr(item, "transaction_id", None)
            if order_id is not None and str(item_order_id) == str(order_id):
                return _result(
                    BrokerReconciliationState.CONFIRMED_MATCH,
                    "Simulation order ID matched",
                    broker="simulation",
                    idempotency_key=idempotency_key,
                    item=item,
                    order_id=str(item_order_id),
                    transaction_id=(
                        str(item_transaction_id) if item_transaction_id is not None else None
                    ),
                )
            if (
                transaction_id is not None
                and item_transaction_id is not None
                and str(item_transaction_id) == str(transaction_id)
            ):
                return _result(
                    BrokerReconciliationState.CONFIRMED_MATCH,
                    "Simulation transaction ID matched",
                    broker="simulation",
                    idempotency_key=idempotency_key,
                    item=item,
                    transaction_id=str(item_transaction_id),
                )
        symbol_match = bool(symbol) and any(
            getattr(item, "symbol", "").strip().upper() == symbol.strip().upper()
            for item in (*positions, *history)
        )
        return classify_observation(
            broker_available=True,
            symbol_match=symbol_match,
            broker="simulation",
            idempotency_key=idempotency_key,
        )


class MT5ReconciliationAdapter:
    """Conservative MT5 evidence lookup, isolated from the generic executor."""

    def __init__(self, gateway: MT5ObservationGateway, *, ledger: PositionLedger | None = None, broker: str = "mt5") -> None:
        self._gateway = gateway
        self._ledger = ledger
        self._broker = broker

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
            ledger_entries = () if self._ledger is None else self._ledger.open_entries(broker=self._broker)
        except Exception:
            return _result(BrokerReconciliationState.UNAVAILABLE, f"{self._broker} state unavailable", broker=self._broker, idempotency_key=idempotency_key)
        records = (*positions, *history)
        if order_id is not None:
            ledger_positions = {
                str(entry.position_id)
                for entry in ledger_entries
                if str(entry.order_id) == str(order_id)
            }
            for item in records:
                observed_position = getattr(item, "position_id", None) or getattr(item, "trade_id", None)
                if observed_position is not None and str(observed_position) in ledger_positions:
                    return _result(
                        BrokerReconciliationState.CONFIRMED_MATCH,
                        "MT5 ledger order mapped to authoritative broker position",
                        broker=self._broker, idempotency_key=idempotency_key, item=item,
                        order_id=order_id, position_id=str(observed_position),
                    )
        for item in records:
            if _matches_id(item, order_id, ("order_id", "order")) or _matches_id(item, deal_id, ("deal_id", "deal", "trade_id")) or _matches_id(item, position_id, ("position_id", "position_identifier")) or _matches_id(item, request_id, ("request_id",)):
                return _result(BrokerReconciliationState.CONFIRMED_MATCH, f"{self._broker} broker identifier matched", broker=self._broker, idempotency_key=idempotency_key, item=item, order_id=order_id, deal_id=deal_id, position_id=position_id, request_id=request_id)
        evidence_present = bool(records) and any(_has_evidence(item) for item in records)
        if evidence_present or symbol:
            return _result(BrokerReconciliationState.AMBIGUOUS, f"{self._broker} evidence lacks intent correlation", broker=self._broker, idempotency_key=idempotency_key, symbol=symbol)
        return _result(BrokerReconciliationState.CONFIRMED_ABSENCE, f"{self._broker} query returned no usable evidence", broker=self._broker, idempotency_key=idempotency_key)


class WeltradeReconciliationAdapter(MT5ReconciliationAdapter):
    """Weltrade reconciliation uses authoritative MT5 tickets and deals."""

    def __init__(self, gateway: MT5ObservationGateway, *, ledger: PositionLedger | None = None, broker: str = "weltrade") -> None:
        super().__init__(gateway, ledger=ledger, broker=broker)


def get_reconciliation_adapter(*, broker: str, gateway: object, ledger: PositionLedger | None = None) -> object:
    """Construct the broker-specific reconciler for the active gateway."""
    normalized = broker.strip().lower()
    if normalized == "simulation":
        return SimulationReconciliationAdapter(gateway)  # type: ignore[arg-type]
    if normalized in {"mt5", "mt5_demo"}:
        return MT5ReconciliationAdapter(gateway, ledger=ledger, broker=normalized)  # type: ignore[arg-type]
    if normalized in {"weltrade", "weltrade_demo"}:
        return WeltradeReconciliationAdapter(gateway, ledger=ledger, broker=normalized)  # type: ignore[arg-type]
    if normalized in {"deriv", "deriv_demo"}:
        return DerivReconciliationAdapter(gateway)  # type: ignore[arg-type]
    raise ValueError(f"Unsupported reconciliation broker: {broker!r}")


def classify_observation(*, broker_available: bool, symbol_match: bool, broker: str = "unknown", idempotency_key: str | None = None) -> BrokerReconciliationResult:
    """Classify evidence without claiming symbol/side correlation."""
    if not broker_available:
        return _result(BrokerReconciliationState.UNAVAILABLE, "Broker state unavailable", broker=broker, idempotency_key=idempotency_key)
    if symbol_match:
        return _result(BrokerReconciliationState.AMBIGUOUS, "Symbol match lacks intent correlation", broker=broker, idempotency_key=idempotency_key)
    return _result(BrokerReconciliationState.AMBIGUOUS, "Broker absence does not prove non-execution", broker=broker, idempotency_key=idempotency_key)


def _normalize_identifier(value: object | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


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
