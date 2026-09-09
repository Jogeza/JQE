"""Explicit safety state for live-paper trading campaigns.

Unlike offline historical research, LivePaperSafetyContext does not assume
mock broker state or fixed zero daily loss; it is hydrated from broker-reported
state before each execution evaluation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from execution.policy import ExecutionContext, PositionSnapshot
from research.historical_safety import ExecutionContextKind


@dataclass(frozen=True, slots=True)
class LivePaperSafetyContext:
    """Declared safety parameters for live-paper broker execution."""

    symbol: str
    broker: str
    account_id: str
    max_daily_loss_percent: float
    max_daily_trades: int
    max_open_positions: int = 1
    environment: str = "demo"
    kind: ExecutionContextKind = ExecutionContextKind.LIVE_PAPER

    def __post_init__(self) -> None:
        if self.kind is not ExecutionContextKind.LIVE_PAPER:
            raise ValueError("live-paper campaign requires explicit LIVE_PAPER context")
        if not self.symbol.strip():
            raise ValueError("live-paper research symbol is required")
        if not self.account_id.strip():
            raise ValueError("live-paper account_id is required")
        if self.broker not in {"mt5_demo", "deriv_demo"}:
            raise ValueError(f"live-paper broker must be mt5_demo or deriv_demo, got {self.broker}")
        if self.max_daily_loss_percent <= 0 or self.max_daily_trades <= 0 or self.max_open_positions <= 0:
            raise ValueError("live-paper safety limits must be positive")

    @property
    def assumptions(self) -> dict[str, object]:
        return {
            "offline_local_only": False,
            "broker_execution_enabled": True,
            "emergency_stop": "FAIL_CLOSED_BROKER_INSPECTION",
            "position_source": "BROKER_OWN_POSITIONS_RECONCILED",
            "idempotency_source": "DURABLE_SQLITE_INTENT_STORE",
        }

    def execution_context(
        self,
        *,
        emergency_stop: bool = False,
        daily_loss_percent: float = 0.0,
        daily_trade_count: int = 0,
        open_positions: tuple[PositionSnapshot, ...] = (),
        used_idempotency_keys: frozenset[str] = frozenset(),
        daily_state_authoritative: bool = True,
    ) -> ExecutionContext:
        """Project current broker and safety state into an ExecutionContext DTO."""
        normalized_symbol = self.symbol.strip().upper()
        return ExecutionContext(
            emergency_stop=emergency_stop,
            daily_loss_percent=daily_loss_percent,
            max_daily_loss_percent=self.max_daily_loss_percent,
            daily_trade_count=daily_trade_count,
            max_daily_trades=self.max_daily_trades,
            open_positions=open_positions,
            max_open_positions=self.max_open_positions,
            used_idempotency_keys=used_idempotency_keys,
            execution_enabled=True,
            dry_run=False,
            broker=self.broker,
            environment=self.environment,
            account_id=self.account_id,
            approved_brokers=frozenset({self.broker}),
            approved_environments=frozenset({self.environment, "demo", "development"}),
            approved_accounts=frozenset({self.account_id}),
            approved_symbols=frozenset({normalized_symbol}),
            daily_state_authoritative=daily_state_authoritative,
        )


def require_live_paper_context(
    context: LivePaperSafetyContext | None,
) -> LivePaperSafetyContext:
    if context is None:
        raise ValueError("LIVE_PAPER safety context is required")
    if context.kind is not ExecutionContextKind.LIVE_PAPER:
        raise ValueError("non-live-paper safety context rejected for live-paper campaign")
    return context
