"""Explicit, deterministic safety state for offline historical research.

This module is intentionally separate from runtime configuration.  Historical
research callers must select this context explicitly; no value is read from
``config.settings`` or from a broker/machine safety snapshot.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from execution.policy import ExecutionContext, PositionSnapshot


class ExecutionContextKind(str, Enum):
    RUNTIME_EXECUTION = "RUNTIME_EXECUTION"
    HISTORICAL_RESEARCH = "HISTORICAL_RESEARCH"


@dataclass(frozen=True, slots=True)
class HistoricalResearchSafetyContext:
    """Declared assumptions used only by deterministic, local paper research."""

    kind: ExecutionContextKind
    symbol: str
    max_daily_loss_percent: float
    max_daily_trades: int
    max_open_positions: int = 1
    emergency_stop_clear: bool = True
    daily_state_authoritative: bool = True
    broker: str = "simulation"
    environment: str = "historical_research"
    account_id: str = "HISTORICAL_RESEARCH"

    def __post_init__(self) -> None:
        if self.kind is not ExecutionContextKind.HISTORICAL_RESEARCH:
            raise ValueError("historical campaign requires explicit HISTORICAL_RESEARCH context")
        if not self.symbol.strip():
            raise ValueError("historical research symbol is required")
        if not self.emergency_stop_clear or not self.daily_state_authoritative:
            raise ValueError("historical research safety assumptions must be explicit and authoritative")
        if self.max_daily_loss_percent <= 0 or self.max_daily_trades <= 0 or self.max_open_positions <= 0:
            raise ValueError("historical research safety limits must be positive")

    @property
    def assumptions(self) -> dict[str, object]:
        return {
            "offline_local_only": True,
            "broker_execution_enabled": False,
            "emergency_stop": "CLEAR_DETERMINISTIC_RESEARCH_ASSUMPTION",
            "daily_loss_percent": 0.0,
            "daily_trade_count": 0,
            "position_source": "DETERMINISTIC_PAPER_CONTRACT_ENGINE",
            "idempotency_source": "DURABLE_RESEARCH_INTENT_STORE",
        }

    def execution_context(
        self,
        *,
        open_positions: tuple[PositionSnapshot, ...] = (),
        used_idempotency_keys: frozenset[str] = frozenset(),
    ) -> ExecutionContext:
        """Project declared research assumptions into the unchanged policy DTO."""

        return ExecutionContext(
            emergency_stop=False,
            daily_loss_percent=0.0,
            max_daily_loss_percent=self.max_daily_loss_percent,
            daily_trade_count=0,
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
            approved_environments=frozenset({self.environment}),
            approved_accounts=frozenset({self.account_id}),
            approved_symbols=frozenset({self.symbol.strip().upper()}),
            daily_state_authoritative=True,
        )


def require_historical_research_context(
    context: HistoricalResearchSafetyContext | None,
) -> HistoricalResearchSafetyContext:
    if context is None:
        raise ValueError("HISTORICAL_RESEARCH safety context is required")
    if context.kind is not ExecutionContextKind.HISTORICAL_RESEARCH:
        raise ValueError("ambiguous or runtime safety context rejected for historical research")
    return context
