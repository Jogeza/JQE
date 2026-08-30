"""Pure, fail-closed policy for authorizing a new execution intent.

This module deliberately performs no broker I/O and owns no position state.
Callers must supply a current broker-derived safety context.  The policy only
answers whether an intent may proceed to a future execution boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
from numbers import Real

from broker.types import OrderSide


class ExecutionDecisionCode(str, Enum):
    """Stable machine-readable outcomes returned by :class:`ExecutionPolicy`."""

    ALLOWED = "ALLOWED"
    EMERGENCY_STOP = "EMERGENCY_STOP"
    RISK_NOT_APPROVED = "RISK_NOT_APPROVED"
    SAFETY_CONTEXT_MISSING = "SAFETY_CONTEXT_MISSING"
    SAFETY_CONTEXT_INVALID = "SAFETY_CONTEXT_INVALID"
    INVALID_DIRECTION = "INVALID_DIRECTION"
    INVALID_VOLUME = "INVALID_VOLUME"
    INVALID_PRICE_LEVELS = "INVALID_PRICE_LEVELS"
    BUY_LEVEL_INVARIANT = "BUY_LEVEL_INVARIANT"
    SELL_LEVEL_INVARIANT = "SELL_LEVEL_INVARIANT"
    DAILY_LOSS_LIMIT = "DAILY_LOSS_LIMIT"
    DAILY_TRADE_LIMIT = "DAILY_TRADE_LIMIT"
    MAX_OPEN_POSITIONS = "MAX_OPEN_POSITIONS"
    DUPLICATE_SYMBOL_POSITION = "DUPLICATE_SYMBOL_POSITION"
    IDEMPOTENCY_KEY_REUSED = "IDEMPOTENCY_KEY_REUSED"
    DEPLOYMENT_NOT_AUTHORIZED = "DEPLOYMENT_NOT_AUTHORIZED"
    DAILY_STATE_NOT_AUTHORITATIVE = "DAILY_STATE_NOT_AUTHORITATIVE"
    EXECUTION_RESERVATION_HELD = "EXECUTION_RESERVATION_HELD"
    EXECUTION_RESERVATION_UNAVAILABLE = "EXECUTION_RESERVATION_UNAVAILABLE"
    UNRESOLVED_DURABLE_INTENT = "UNRESOLVED_DURABLE_INTENT"


@dataclass(frozen=True, slots=True)
class ExecutionIntent:
    """A proposed order plus the explicit result of upstream risk approval."""

    symbol: str
    side: OrderSide | str
    volume: float
    entry: float
    stop_loss: float
    take_profit: float
    idempotency_key: str
    risk_approved: bool | None


@dataclass(frozen=True, slots=True)
class PositionSnapshot:
    """Minimal immutable broker-position state consumed by the policy.

    A later broker-state coordinator is responsible for converting broker
    DTOs into these snapshots.  The pure policy performs no such conversion.
    """

    symbol: str
    side: OrderSide | str


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    """Broker-derived and configured safety state required by the policy.

    ``open_positions`` and ``used_idempotency_keys`` are snapshots supplied by
    the caller.  The policy never mutates or treats them as an authoritative
    ledger.
    """

    emergency_stop: bool | None
    daily_loss_percent: float | None
    max_daily_loss_percent: float | None
    daily_trade_count: int | None
    max_daily_trades: int | None
    open_positions: tuple[PositionSnapshot, ...] | None
    max_open_positions: int | None
    used_idempotency_keys: frozenset[str] | None
    execution_enabled: bool = False
    dry_run: bool = True
    broker: str | None = None
    environment: str | None = None
    account_id: str | None = None
    approved_brokers: frozenset[str] = frozenset()
    approved_environments: frozenset[str] = frozenset()
    approved_accounts: frozenset[str] = frozenset()
    approved_symbols: frozenset[str] = frozenset()
    daily_state_authoritative: bool = False


@dataclass(frozen=True, slots=True)
class ExecutionDecision:
    """Deterministic policy result with a stable code and readable reason."""

    allowed: bool
    code: ExecutionDecisionCode
    reason: str


def _is_finite_number(value: object) -> bool:
    return isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(float(value))


def _valid_position_snapshot(snapshot: object) -> bool:
    return (
        isinstance(snapshot, PositionSnapshot)
        and isinstance(snapshot.symbol, str)
        and bool(snapshot.symbol.strip())
        and snapshot.side in (OrderSide.BUY, OrderSide.SELL)
    )


def _reject(code: ExecutionDecisionCode, reason: str) -> ExecutionDecision:
    return ExecutionDecision(allowed=False, code=code, reason=reason)


class ExecutionPolicy:
    """Evaluates new-order safety checks in a fixed, fail-closed order."""

    @staticmethod
    def evaluate(
        intent: ExecutionIntent,
        context: ExecutionContext | None,
    ) -> ExecutionDecision:
        # 1. Emergency stop has absolute precedence when readable.
        if context is not None and context.emergency_stop is True:
            return _reject(ExecutionDecisionCode.EMERGENCY_STOP, "Emergency stop is active")

        # 2. Upstream risk must explicitly approve; truthy substitutes fail.
        if intent.risk_approved is not True:
            return _reject(
                ExecutionDecisionCode.RISK_NOT_APPROVED,
                "Explicit upstream risk approval is required",
            )

        # 3. Every required safety-state field must be present and valid.
        if context is None:
            return _reject(
                ExecutionDecisionCode.SAFETY_CONTEXT_MISSING,
                "Execution safety context is missing",
            )

        context_valid = (
            isinstance(context.emergency_stop, bool)
            and _is_finite_number(context.daily_loss_percent)
            and float(context.daily_loss_percent) >= 0
            and _is_finite_number(context.max_daily_loss_percent)
            and float(context.max_daily_loss_percent) > 0
            and isinstance(context.daily_trade_count, int)
            and not isinstance(context.daily_trade_count, bool)
            and context.daily_trade_count >= 0
            and isinstance(context.max_daily_trades, int)
            and not isinstance(context.max_daily_trades, bool)
            and context.max_daily_trades > 0
            and isinstance(context.open_positions, tuple)
            and all(_valid_position_snapshot(position) for position in context.open_positions)
            and isinstance(context.max_open_positions, int)
            and not isinstance(context.max_open_positions, bool)
            and context.max_open_positions > 0
            and isinstance(context.used_idempotency_keys, frozenset)
            and all(isinstance(key, str) and bool(key.strip()) for key in context.used_idempotency_keys)
            and isinstance(context.execution_enabled, bool)
            and isinstance(context.dry_run, bool)
            and isinstance(context.broker, str)
            and bool(context.broker.strip())
            and isinstance(context.environment, str)
            and bool(context.environment.strip())
            and isinstance(context.account_id, str)
            and bool(context.account_id.strip())
            and all(
                isinstance(values, frozenset)
                and all(isinstance(value, str) and bool(value.strip()) for value in values)
                for values in (
                    context.approved_brokers,
                    context.approved_environments,
                    context.approved_accounts,
                    context.approved_symbols,
                )
            )
            and isinstance(context.daily_state_authoritative, bool)
            and isinstance(intent.symbol, str)
            and bool(intent.symbol.strip())
            and isinstance(intent.idempotency_key, str)
            and bool(intent.idempotency_key.strip())
        )
        if not context_valid:
            return _reject(
                ExecutionDecisionCode.SAFETY_CONTEXT_INVALID,
                "Execution safety context is incomplete or invalid",
            )

        deployment_authorized = (
            context.execution_enabled is True
            and context.dry_run is False
            and isinstance(context.broker, str)
            and context.broker in context.approved_brokers
            and isinstance(context.environment, str)
            and context.environment in context.approved_environments
            and isinstance(context.account_id, str)
            and context.account_id in context.approved_accounts
            and intent.symbol.strip().upper() in context.approved_symbols
        )
        if not deployment_authorized:
            return _reject(
                ExecutionDecisionCode.DEPLOYMENT_NOT_AUTHORIZED,
                "Deployment authorization is incomplete or denied",
            )
        if context.daily_state_authoritative is not True:
            return _reject(
                ExecutionDecisionCode.DAILY_STATE_NOT_AUTHORITATIVE,
                "Daily loss and trade counters are not authoritative",
            )

        # 4. Only canonical directional signals are executable.
        if intent.side not in (OrderSide.BUY, OrderSide.SELL):
            return _reject(ExecutionDecisionCode.INVALID_DIRECTION, "Direction must be BUY or SELL")

        # 5. Volume must be a positive finite financial value.
        if not _is_finite_number(intent.volume) or float(intent.volume) <= 0:
            return _reject(ExecutionDecisionCode.INVALID_VOLUME, "Volume must be positive and finite")

        # 6. Every price must be positive, finite, and obey the directional invariant.
        if not all(
            _is_finite_number(value) and float(value) > 0
            for value in (intent.entry, intent.stop_loss, intent.take_profit)
        ):
            return _reject(
                ExecutionDecisionCode.INVALID_PRICE_LEVELS,
                "Entry, stop loss, and take profit must be positive and finite",
            )
        if intent.side == OrderSide.BUY and not (
            intent.stop_loss < intent.entry < intent.take_profit
        ):
            return _reject(
                ExecutionDecisionCode.BUY_LEVEL_INVARIANT,
                "BUY requires stop_loss < entry < take_profit",
            )
        if intent.side == OrderSide.SELL and not (
            intent.take_profit < intent.entry < intent.stop_loss
        ):
            return _reject(
                ExecutionDecisionCode.SELL_LEVEL_INVARIANT,
                "SELL requires take_profit < entry < stop_loss",
            )

        # 7-9. Limits reject at the configured boundary, not after it.
        if context.daily_loss_percent >= context.max_daily_loss_percent:
            return _reject(ExecutionDecisionCode.DAILY_LOSS_LIMIT, "Daily loss limit reached")
        if context.daily_trade_count >= context.max_daily_trades:
            return _reject(ExecutionDecisionCode.DAILY_TRADE_LIMIT, "Daily trade limit reached")
        if len(context.open_positions) >= context.max_open_positions:
            return _reject(ExecutionDecisionCode.MAX_OPEN_POSITIONS, "Maximum open positions reached")

        # 10. Conservative policy: any same-symbol position blocks another.
        normalized_symbol = intent.symbol.strip().upper()
        if any(position.symbol.strip().upper() == normalized_symbol for position in context.open_positions):
            return _reject(
                ExecutionDecisionCode.DUPLICATE_SYMBOL_POSITION,
                "An open position already exists for this symbol",
            )

        # 11. Submission-intent identifiers are single-use.
        if intent.idempotency_key in context.used_idempotency_keys:
            return _reject(
                ExecutionDecisionCode.IDEMPOTENCY_KEY_REUSED,
                "Idempotency key has already been used",
            )

        return ExecutionDecision(
            allowed=True,
            code=ExecutionDecisionCode.ALLOWED,
            reason="Execution policy passed",
        )
