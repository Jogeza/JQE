"""Deterministic offline paper-contract lifecycle bound to closed candles."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Iterable

from broker.types import (
    ClosedMarketObservation,
    OrderRequest,
    OrderResult,
    OrderSide,
    OrderStatus,
    Position,
)
from execution.contract_lifecycle import ContractLifecycleState
from execution.policy import ExecutionContext, ExecutionIntent, ExecutionPolicy


class PaperExitReason(str, Enum):
    STOP_LOSS = "STOP_LOSS"
    TAKE_PROFIT = "TAKE_PROFIT"
    STRATEGY_EXIT = "STRATEGY_EXIT"
    END_OF_TEST = "END_OF_TEST"


def _money(value: Decimal, name: str, *, nonnegative: bool = False) -> Decimal:
    if type(value) is not Decimal or not value.is_finite() or (nonnegative and value < 0):
        raise ValueError(f"{name} must be a finite Decimal")
    return value


@dataclass(frozen=True, slots=True)
class PaperContractSpecification:
    minimum_stake: Decimal = Decimal("0.01")
    maximum_stake: Decimal = Decimal("1000000")
    stake_increment: Decimal = Decimal("0.01")
    fee_rate: Decimal = Decimal("0")
    slippage: Decimal = Decimal("0")
    quantity_basis: str = "SIMULATION_STAKE"

    def __post_init__(self) -> None:
        for name in ("minimum_stake", "maximum_stake", "stake_increment"):
            if _money(getattr(self, name), name) <= 0:
                raise ValueError(f"{name} must be positive")
        _money(self.fee_rate, "fee_rate", nonnegative=True)
        _money(self.slippage, "slippage", nonnegative=True)
        if self.maximum_stake < self.minimum_stake:
            raise ValueError("maximum stake cannot be below minimum")
        if self.quantity_basis != "SIMULATION_STAKE":
            raise ValueError("paper quantity basis must be SIMULATION_STAKE")

    def validate_stake(self, stake: Decimal) -> None:
        _money(stake, "stake")
        if stake < self.minimum_stake or stake > self.maximum_stake:
            raise ValueError("stake is outside configured limits")
        if (stake - self.minimum_stake) % self.stake_increment != 0:
            raise ValueError("stake does not align to configured increment")

    def fee(self, price: Decimal, stake: Decimal) -> Decimal:
        return abs(price * stake) * self.fee_rate


@dataclass(frozen=True, slots=True)
class PaperProposal:
    proposal_id: str
    idempotency_key: str
    symbol: str
    side: OrderSide
    stake: Decimal
    entry: Decimal
    stop_loss: Decimal
    take_profit: Decimal
    observation_closed_at: datetime
    maximum_loss: Decimal


@dataclass(frozen=True, slots=True)
class PaperPosition:
    contract_id: str
    proposal_id: str
    idempotency_key: str
    symbol: str
    side: OrderSide
    stake: Decimal
    entry: Decimal
    stop_loss: Decimal
    take_profit: Decimal
    opened_at: datetime
    last_observed_at: datetime
    state: ContractLifecycleState
    close_requested: bool = False


@dataclass(frozen=True, slots=True)
class PaperClose:
    contract_id: str
    close_id: str
    reason: PaperExitReason
    exit_price: Decimal
    closed_at: datetime
    gross_profit: Decimal
    fees: Decimal
    realized_profit: Decimal
    state: ContractLifecycleState = ContractLifecycleState.CLOSED


@dataclass(frozen=True, slots=True)
class PaperReconciliation:
    state: ContractLifecycleState
    contract_id: str
    close_id: str | None
    realized_profit: Decimal | None


class PaperContractEngine:
    """One deterministic, in-memory paper venue with no broker connectivity."""

    def __init__(self, specification: PaperContractSpecification | None = None) -> None:
        self.specification = specification or PaperContractSpecification()
        self._proposals: dict[str, PaperProposal] = {}
        self._positions: dict[str, PaperPosition] = {}
        self._closes: dict[str, PaperClose] = {}

    @property
    def positions(self) -> tuple[PaperPosition, ...]:
        return tuple(self._positions.values())

    def get_position(self, contract_id: str) -> PaperPosition:
        return self._positions[contract_id]

    @property
    def positions(self) -> tuple[PaperPosition, ...]:
        return tuple(self._positions.values())

    def get_position(self, contract_id: str) -> PaperPosition:
        return self._positions[contract_id]

    @staticmethod
    def _d(value: float) -> Decimal:
        return Decimal(str(value))

    def propose(
        self, *, idempotency_key: str, side: OrderSide, stake: Decimal,
        stop_loss: Decimal, take_profit: Decimal, observation: ClosedMarketObservation,
    ) -> PaperProposal:
        self.specification.validate_stake(stake)
        entry = self._d(observation.reference_price)
        if side is OrderSide.BUY and not stop_loss < entry < take_profit:
            raise ValueError("BUY paper levels are invalid")
        if side is OrderSide.SELL and not take_profit < entry < stop_loss:
            raise ValueError("SELL paper levels are invalid")
        slipped_stop = (
            stop_loss - self.specification.slippage
            if side is OrderSide.BUY
            else stop_loss + self.specification.slippage
        )
        loss_at_stop = abs(entry - slipped_stop) * stake
        fees = self.specification.fee(entry, stake) + self.specification.fee(slipped_stop, stake)
        proposal = PaperProposal(
            f"PAPER-P-{idempotency_key}", idempotency_key,
            observation.canonical_symbol, side, stake, entry, stop_loss, take_profit,
            observation.closed_at, loss_at_stop + fees,
        )
        existing = self._proposals.get(idempotency_key)
        if existing is not None:
            if existing != proposal:
                raise ValueError("paper idempotency context mismatch")
            return existing
        self._proposals[idempotency_key] = proposal
        return proposal

    def authorize_and_propose(
        self, intent: ExecutionIntent, context: ExecutionContext,
        observation: ClosedMarketObservation, *, observed_at: datetime,
    ) -> PaperProposal:
        decision = ExecutionPolicy.evaluate(intent, context)
        if not decision.allowed:
            raise ValueError(f"paper trade blocked: {decision.code.value}")
        if intent.symbol.strip().upper() != observation.canonical_symbol.strip().upper():
            raise ValueError("paper intent symbol does not match the closed observation")
        if not observation.is_closed_at(observed_at):
            raise ValueError("paper market observation is not closed")
        if intent.quantity is None:
            raise ValueError("paper stake is missing")
        stake = Decimal(str(intent.quantity.value))
        proposal = self.propose(
            idempotency_key=intent.idempotency_key,
            side=intent.side,
            stake=stake,
            stop_loss=Decimal(str(intent.stop_loss)),
            take_profit=Decimal(str(intent.take_profit)),
            observation=observation,
        )
        if proposal.entry != Decimal(str(intent.entry)):
            raise ValueError("intent entry is not bound to the closed observation")
        if intent.authorized_risk_amount is None or proposal.maximum_loss > Decimal(str(intent.authorized_risk_amount)):
            raise ValueError("paper maximum loss exceeds authorized risk")
        return proposal

    def open(self, proposal: PaperProposal) -> PaperPosition:
        contract_id = f"PAPER-C-{proposal.idempotency_key}"
        if contract_id in self._positions:
            raise ValueError("paper contract is already open")
        position = PaperPosition(
            contract_id, proposal.proposal_id, proposal.idempotency_key,
            proposal.symbol, proposal.side, proposal.stake, proposal.entry,
            proposal.stop_loss, proposal.take_profit, proposal.observation_closed_at,
            proposal.observation_closed_at, ContractLifecycleState.PURCHASED_OPEN,
        )
        self._positions[contract_id] = position
        return position

    def request_close(self, contract_id: str) -> PaperPosition:
        position = self._positions[contract_id]
        if contract_id in self._closes or position.close_requested:
            raise ValueError("paper close is already requested or completed")
        updated = replace(position, close_requested=True, state=ContractLifecycleState.CLOSE_REQUESTED)
        self._positions[contract_id] = updated
        return updated

    def observe(
        self, contract_id: str, observation: ClosedMarketObservation,
        *, strategy_exit: bool = False, force_close: bool = False,
    ) -> PaperClose | None:
        position = self._positions[contract_id]
        if contract_id in self._closes:
            raise ValueError("paper contract is already closed")
        if observation.canonical_symbol != position.symbol:
            raise ValueError("paper observation symbol mismatch")
        if observation.closed_at <= position.last_observed_at:
            raise ValueError("paper observations must be strictly chronological")
        opened = self._d(observation.open)
        high = self._d(observation.high)
        low = self._d(observation.low)
        close = self._d(observation.close)
        reason: PaperExitReason | None = None
        price: Decimal | None = None
        if position.side is OrderSide.BUY:
            if opened <= position.stop_loss:
                reason, price = PaperExitReason.STOP_LOSS, opened
            elif opened >= position.take_profit:
                reason, price = PaperExitReason.TAKE_PROFIT, opened
            elif low <= position.stop_loss:
                reason, price = PaperExitReason.STOP_LOSS, position.stop_loss
            elif high >= position.take_profit:
                reason, price = PaperExitReason.TAKE_PROFIT, position.take_profit
        else:
            if opened >= position.stop_loss:
                reason, price = PaperExitReason.STOP_LOSS, opened
            elif opened <= position.take_profit:
                reason, price = PaperExitReason.TAKE_PROFIT, opened
            elif high >= position.stop_loss:
                reason, price = PaperExitReason.STOP_LOSS, position.stop_loss
            elif low <= position.take_profit:
                reason, price = PaperExitReason.TAKE_PROFIT, position.take_profit
        if reason is None and strategy_exit:
            reason, price = PaperExitReason.STRATEGY_EXIT, close
        if reason is None and force_close:
            reason, price = PaperExitReason.END_OF_TEST, close
        if reason is None:
            self._positions[contract_id] = replace(position, last_observed_at=observation.closed_at)
            return None
        slippage = self.specification.slippage
        price = price - slippage if position.side is OrderSide.BUY else price + slippage
        direction = Decimal("1") if position.side is OrderSide.BUY else Decimal("-1")
        gross = (price - position.entry) * position.stake * direction
        fees = self.specification.fee(position.entry, position.stake) + self.specification.fee(price, position.stake)
        result = PaperClose(
            contract_id, f"PAPER-X-{position.idempotency_key}", reason, price,
            observation.closed_at, gross, fees, gross - fees,
        )
        self._closes[contract_id] = result
        self._positions[contract_id] = replace(
            position, last_observed_at=observation.closed_at,
            close_requested=True, state=ContractLifecycleState.CLOSED,
        )
        return result

    def replay(
        self, contract_id: str, observations: Iterable[ClosedMarketObservation],
        *, force_close: bool = True,
    ) -> PaperClose | None:
        ordered = list(observations)
        result = None
        for index, observation in enumerate(ordered):
            result = self.observe(
                contract_id, observation,
                force_close=force_close and index == len(ordered) - 1,
            )
            if result is not None:
                return result
        return result

    def reconcile(self, contract_id: str) -> PaperReconciliation:
        position = self._positions.get(contract_id)
        if position is None:
            return PaperReconciliation(ContractLifecycleState.SUBMISSION_UNKNOWN, contract_id, None, None)
        closed = self._closes.get(contract_id)
        if closed is not None:
            return PaperReconciliation(ContractLifecycleState.CLOSED, contract_id, closed.close_id, closed.realized_profit)
        return PaperReconciliation(position.state, contract_id, None, None)


class PaperContractExecutionGateway:
    """Offline venue adapter used exclusively through ``AsyncTradeExecutor``."""

    def __init__(
        self,
        engine: PaperContractEngine,
        observation: ClosedMarketObservation,
        *,
        observed_at: datetime,
        authorized_risk_amount: Decimal,
    ) -> None:
        if not observation.is_closed_at(observed_at):
            raise ValueError("paper market observation is not closed")
        self.engine = engine
        self.observation = observation
        self.observed_at = observed_at
        self.authorized_risk_amount = _money(
            authorized_risk_amount, "authorized_risk_amount", nonnegative=True
        )

    async def get_positions(self) -> list[Position]:
        return [
            Position(
                position_id=item.contract_id,
                symbol=item.symbol,
                side=item.side,
                volume=float(item.stake),
                open_price=float(item.entry),
                stop_loss=float(item.stop_loss),
                take_profit=float(item.take_profit),
                opened_at=item.opened_at,
            )
            for item in self.engine._positions.values()
            if item.state is not ContractLifecycleState.CLOSED
        ]

    async def submit_order(self, order: OrderRequest) -> OrderResult:
        if order.symbol.strip().upper() != self.observation.canonical_symbol.strip().upper():
            raise ValueError("paper order symbol does not match the closed observation")
        proposal = self.engine.propose(
            idempotency_key=order.idempotency_key or "",
            side=order.side,
            stake=Decimal(str(order.quantity.value)),
            stop_loss=Decimal(str(order.stop_loss)),
            take_profit=Decimal(str(order.take_profit)),
            observation=self.observation,
        )
        if proposal.maximum_loss > self.authorized_risk_amount:
            raise ValueError("paper maximum loss exceeds authorized risk")
        position = self.engine.open(proposal)
        return OrderResult(
            order_id=position.contract_id,
            status=OrderStatus.FILLED,
            symbol=position.symbol,
            side=position.side,
            volume=float(position.stake),
            filled_price=float(position.entry),
            raw={"paper": True, "network": False},
        )
