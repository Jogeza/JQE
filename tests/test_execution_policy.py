"""Focused tests for the pure, fail-closed Phase 6 execution policy."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from unittest.mock import MagicMock

import pytest

from broker.types import OrderSide
from execution.policy import (
    ExecutionContext,
    ExecutionDecisionCode,
    ExecutionIntent,
    ExecutionPolicy,
    PositionSnapshot,
)


def _intent(**overrides: object) -> ExecutionIntent:
    base = ExecutionIntent(
        symbol="XAUUSD",
        side=OrderSide.BUY,
        volume=0.25,
        entry=2000.0,
        stop_loss=1990.0,
        take_profit=2020.0,
        idempotency_key="intent-001",
        risk_approved=True,
    )
    return replace(base, **overrides)


def _position(
    symbol: object = "EURUSD", side: object = OrderSide.BUY
) -> PositionSnapshot:
    base = PositionSnapshot(symbol="EURUSD", side=OrderSide.BUY)
    return replace(base, symbol=symbol, side=side)


def _context(**overrides: object) -> ExecutionContext:
    base = ExecutionContext(
        emergency_stop=False,
        daily_loss_percent=0.5,
        max_daily_loss_percent=3.0,
        daily_trade_count=1,
        max_daily_trades=5,
        open_positions=(),
        max_open_positions=3,
        used_idempotency_keys=frozenset(),
        execution_enabled=True,
        dry_run=False,
        broker="mt5",
        environment="demo",
        account_id="demo-account",
        approved_brokers=frozenset({"mt5"}),
        approved_environments=frozenset({"demo"}),
        approved_accounts=frozenset({"demo-account"}),
        approved_symbols=frozenset({"XAUUSD"}),
        daily_state_authoritative=True,
    )
    return replace(base, **overrides)


def _code(intent: ExecutionIntent, context: ExecutionContext | None) -> ExecutionDecisionCode:
    return ExecutionPolicy.evaluate(intent, context).code


class TestPrecedenceAndApproval:
    def test_explicit_clear_passes_emergency_stop_gate(self) -> None:
        decision = ExecutionPolicy.evaluate(_intent(), _context(emergency_stop=False))
        assert decision.allowed is True

    def test_emergency_stop_has_precedence_over_every_other_failure(self) -> None:
        decision = ExecutionPolicy.evaluate(
            _intent(risk_approved=False, side="HOLD", volume=0),
            _context(emergency_stop=True, daily_loss_percent=99.0),
        )
        assert decision.allowed is False
        assert decision.code is ExecutionDecisionCode.EMERGENCY_STOP

    def test_unknown_emergency_stop_fails_closed(self) -> None:
        decision = ExecutionPolicy.evaluate(_intent(), _context(emergency_stop=None))
        assert decision.allowed is False
        assert decision.code is ExecutionDecisionCode.SAFETY_CONTEXT_INVALID

    @pytest.mark.parametrize("approval", [None, False])
    def test_missing_or_false_risk_approval_rejects(self, approval: bool | None) -> None:
        assert _code(_intent(risk_approved=approval), _context()) is ExecutionDecisionCode.RISK_NOT_APPROVED

    @pytest.mark.parametrize(
        "override",
        [
            {"execution_enabled": False},
            {"dry_run": True},
            {"account_id": "unapproved"},
            {"environment": "live"},
            {"broker": "deriv"},
            {"approved_symbols": frozenset({"EURUSD"})},
        ],
    )
    def test_deployment_authorization_fails_closed(self, override: dict[str, object]) -> None:
        assert _code(_intent(), _context(**override)) is ExecutionDecisionCode.DEPLOYMENT_NOT_AUTHORIZED

    def test_daily_state_must_be_marked_authoritative(self) -> None:
        assert _code(_intent(), _context(daily_state_authoritative=False)) is ExecutionDecisionCode.DAILY_STATE_NOT_AUTHORITATIVE

    @pytest.mark.parametrize("field", ["approved_brokers", "approved_environments", "approved_accounts", "approved_symbols"])
    def test_malformed_deployment_collections_fail_closed(self, field: str) -> None:
        assert _code(_intent(), _context(**{field: None})) is ExecutionDecisionCode.SAFETY_CONTEXT_INVALID

    def test_explicit_risk_rejection_precedes_missing_context(self) -> None:
        assert _code(_intent(risk_approved=False), None) is ExecutionDecisionCode.RISK_NOT_APPROVED

    def test_missing_context_rejects(self) -> None:
        assert _code(_intent(), None) is ExecutionDecisionCode.SAFETY_CONTEXT_MISSING

    @pytest.mark.parametrize(
        "context",
        [
            _context(emergency_stop=None),
            _context(daily_loss_percent=None),
            _context(daily_loss_percent=float("nan")),
            _context(daily_loss_percent=-0.01),
            _context(max_daily_loss_percent=0),
            _context(max_daily_loss_percent=-1),
            _context(max_daily_loss_percent=float("nan")),
            _context(max_daily_loss_percent=float("inf")),
            _context(max_daily_loss_percent=float("-inf")),
            _context(daily_trade_count=None),
            _context(daily_trade_count=-1),
            _context(daily_trade_count=True),
            _context(max_daily_trades=0),
            _context(max_daily_trades=-1),
            _context(max_daily_trades=True),
            _context(open_positions=None),
            _context(max_open_positions=0),
            _context(max_open_positions=-1),
            _context(max_open_positions=True),
            _context(used_idempotency_keys=None),
            _context(used_idempotency_keys=frozenset({""})),
            _context(used_idempotency_keys=frozenset({"   "})),
            _context(used_idempotency_keys=frozenset({1})),
        ],
    )
    def test_unreadable_or_invalid_safety_state_fails_closed(
        self, context: ExecutionContext
    ) -> None:
        assert _code(_intent(), context) is ExecutionDecisionCode.SAFETY_CONTEXT_INVALID


class TestIntentValidation:
    @pytest.mark.parametrize("symbol", ["", " ", "\t\r\n", None, 123])
    def test_blank_or_malformed_symbol_rejects(self, symbol: object) -> None:
        assert _code(_intent(symbol=symbol), _context()) is ExecutionDecisionCode.SAFETY_CONTEXT_INVALID

    @pytest.mark.parametrize("key", ["", " ", "\t\r\n", None, 123])
    def test_blank_or_malformed_idempotency_key_rejects(self, key: object) -> None:
        assert _code(
            _intent(idempotency_key=key), _context()
        ) is ExecutionDecisionCode.SAFETY_CONTEXT_INVALID

    @pytest.mark.parametrize("missing", ["symbol", "idempotency_key"])
    def test_required_identifier_cannot_be_omitted(self, missing: str) -> None:
        values = {
            "symbol": "XAUUSD",
            "side": OrderSide.BUY,
            "volume": 0.25,
            "entry": 2000.0,
            "stop_loss": 1990.0,
            "take_profit": 2020.0,
            "idempotency_key": "intent-001",
            "risk_approved": True,
        }
        del values[missing]
        with pytest.raises(TypeError):
            ExecutionIntent(**values)

    @pytest.mark.parametrize("side", ["HOLD", "buy", "", None])
    def test_invalid_direction_rejects(self, side: object) -> None:
        assert _code(_intent(side=side), _context()) is ExecutionDecisionCode.INVALID_DIRECTION

    @pytest.mark.parametrize(
        "volume",
        [0.0, -0.01, float("nan"), float("inf"), float("-inf"), True, None, "0.25"],
    )
    def test_invalid_volume_rejects(self, volume: object) -> None:
        assert _code(_intent(volume=volume), _context()) is ExecutionDecisionCode.INVALID_VOLUME

    @pytest.mark.parametrize("field", ["entry", "stop_loss", "take_profit"])
    @pytest.mark.parametrize(
        "value",
        [0, -0.01, float("nan"), float("inf"), float("-inf"), True, False, None, "100"],
    )
    def test_non_positive_or_malformed_price_rejects(self, field: str, value: object) -> None:
        assert _code(_intent(**{field: value}), _context()) is ExecutionDecisionCode.INVALID_PRICE_LEVELS

    @pytest.mark.parametrize(
        "side,entry,stop_loss,take_profit",
        [
            (OrderSide.BUY, -2.0, -3.0, -1.0),
            (OrderSide.SELL, -2.0, -1.0, -3.0),
        ],
    )
    def test_all_negative_but_correctly_ordered_levels_reject(
        self, side: OrderSide, entry: float, stop_loss: float, take_profit: float
    ) -> None:
        assert _code(
            _intent(side=side, entry=entry, stop_loss=stop_loss, take_profit=take_profit),
            _context(),
        ) is ExecutionDecisionCode.INVALID_PRICE_LEVELS

    @pytest.mark.parametrize(
        "stop_loss,take_profit",
        [(2000.0, 2020.0), (1990.0, 2000.0), (2010.0, 2020.0)],
    )
    def test_buy_invariant_boundaries_reject(self, stop_loss: float, take_profit: float) -> None:
        assert _code(
            _intent(side=OrderSide.BUY, stop_loss=stop_loss, take_profit=take_profit),
            _context(),
        ) is ExecutionDecisionCode.BUY_LEVEL_INVARIANT

    @pytest.mark.parametrize(
        "stop_loss,take_profit",
        [(2000.0, 1980.0), (2010.0, 2000.0), (1990.0, 1980.0)],
    )
    def test_sell_invariant_boundaries_reject(self, stop_loss: float, take_profit: float) -> None:
        assert _code(
            _intent(side=OrderSide.SELL, stop_loss=stop_loss, take_profit=take_profit),
            _context(),
        ) is ExecutionDecisionCode.SELL_LEVEL_INVARIANT

    def test_valid_sell_levels_pass(self) -> None:
        decision = ExecutionPolicy.evaluate(
            _intent(side=OrderSide.SELL, stop_loss=2010.0, take_profit=1980.0),
            _context(),
        )
        assert decision.allowed is True
        assert decision.code is ExecutionDecisionCode.ALLOWED


class TestLimitsDuplicatesAndIdempotency:
    def test_daily_loss_rejects_at_boundary(self) -> None:
        assert _code(
            _intent(), _context(daily_loss_percent=3.0, max_daily_loss_percent=3.0)
        ) is ExecutionDecisionCode.DAILY_LOSS_LIMIT

    def test_daily_trade_count_rejects_at_boundary(self) -> None:
        assert _code(
            _intent(), _context(daily_trade_count=5, max_daily_trades=5)
        ) is ExecutionDecisionCode.DAILY_TRADE_LIMIT

    @pytest.mark.parametrize(
        "count,expected",
        [
            (2, ExecutionDecisionCode.ALLOWED),
            (3, ExecutionDecisionCode.MAX_OPEN_POSITIONS),
            (4, ExecutionDecisionCode.MAX_OPEN_POSITIONS),
        ],
    )
    def test_open_position_limit_minus_one_at_and_above(
        self, count: int, expected: ExecutionDecisionCode
    ) -> None:
        positions = tuple(_position(f"EURUSD-{index}") for index in range(count))
        assert _code(
            _intent(), _context(open_positions=positions, max_open_positions=3)
        ) is expected

    def test_same_symbol_same_side_rejects(self) -> None:
        assert _code(
            _intent(), _context(open_positions=(_position("XAUUSD", OrderSide.BUY),))
        ) is ExecutionDecisionCode.DUPLICATE_SYMBOL_POSITION

    def test_same_symbol_opposite_side_also_rejects(self) -> None:
        assert _code(
            _intent(), _context(open_positions=(_position("xauusd", OrderSide.SELL),))
        ) is ExecutionDecisionCode.DUPLICATE_SYMBOL_POSITION

    def test_same_symbol_matching_strips_whitespace_and_ignores_case(self) -> None:
        assert _code(
            _intent(symbol=" XauUsd "),
            _context(open_positions=(_position("  xAUuSD  ", OrderSide.SELL),)),
        ) is ExecutionDecisionCode.DUPLICATE_SYMBOL_POSITION

    def test_different_symbol_position_allows(self) -> None:
        assert _code(
            _intent(), _context(open_positions=(_position("EURUSD"),))
        ) is ExecutionDecisionCode.ALLOWED

    def test_repeated_idempotency_key_rejects(self) -> None:
        assert _code(
            _intent(idempotency_key="intent-001"),
            _context(used_idempotency_keys=frozenset({"intent-001"})),
        ) is ExecutionDecisionCode.IDEMPOTENCY_KEY_REUSED

    def test_new_idempotency_key_allows(self) -> None:
        assert _code(
            _intent(idempotency_key="intent-002"),
            _context(used_idempotency_keys=frozenset({"intent-001"})),
        ) is ExecutionDecisionCode.ALLOWED


class TestPositionSnapshotValidation:
    @pytest.mark.parametrize("symbol", ["", " ", "\t\r\n", None, 123])
    def test_blank_or_malformed_position_symbol_fails_closed(self, symbol: object) -> None:
        decision = ExecutionPolicy.evaluate(
            _intent(), _context(open_positions=(_position(symbol=symbol),))
        )
        assert decision.code is ExecutionDecisionCode.SAFETY_CONTEXT_INVALID

    @pytest.mark.parametrize("side", ["HOLD", "buy", "", None, 1])
    def test_invalid_position_direction_fails_closed(self, side: object) -> None:
        decision = ExecutionPolicy.evaluate(
            _intent(), _context(open_positions=(_position(side=side),))
        )
        assert decision.code is ExecutionDecisionCode.SAFETY_CONTEXT_INVALID

    def test_non_snapshot_position_entry_fails_closed_without_exception(self) -> None:
        # Deliberately violate the runtime annotation to prove untrusted nested
        # state is rejected rather than accessed or converted.
        context = replace(_context(), open_positions=(object(),))
        decision = ExecutionPolicy.evaluate(_intent(), context)
        assert decision.code is ExecutionDecisionCode.SAFETY_CONTEXT_INVALID

    def test_malformed_frozen_snapshot_fails_closed_without_exception(self) -> None:
        snapshot = _position()
        # object.__setattr__ deliberately bypasses the dataclass guard to model
        # corrupted runtime/deserialized state; normal callers cannot do this.
        object.__setattr__(snapshot, "symbol", None)
        decision = ExecutionPolicy.evaluate(
            _intent(), _context(open_positions=(snapshot,))
        )
        assert decision.code is ExecutionDecisionCode.SAFETY_CONTEXT_INVALID

    def test_nested_position_snapshot_is_immutable(self) -> None:
        snapshot = _position()
        context = _context(open_positions=(snapshot,))
        with pytest.raises(FrozenInstanceError):
            context.open_positions[0].symbol = "XAUUSD"


class TestPurityAndStability:
    def test_rejection_code_values_are_stable_strings(self) -> None:
        assert ExecutionDecisionCode.EMERGENCY_STOP.value == "EMERGENCY_STOP"
        assert ExecutionDecisionCode.RISK_NOT_APPROVED.value == "RISK_NOT_APPROVED"
        assert ExecutionDecisionCode.IDEMPOTENCY_KEY_REUSED.value == "IDEMPOTENCY_KEY_REUSED"

    def test_same_inputs_produce_identical_decisions(self) -> None:
        intent = _intent()
        context = _context()
        assert ExecutionPolicy.evaluate(intent, context) == ExecutionPolicy.evaluate(intent, context)

    def test_evaluation_does_not_mutate_supplied_state(self) -> None:
        context = _context(
            open_positions=(_position("EURUSD"),),
            used_idempotency_keys=frozenset({"old-key"}),
        )
        before = replace(context)
        ExecutionPolicy.evaluate(_intent(), context)
        assert context == before

    def test_evaluation_performs_no_gateway_call(self, monkeypatch: pytest.MonkeyPatch) -> None:
        gateway_factory = MagicMock(side_effect=AssertionError("gateway construction is forbidden"))
        monkeypatch.setattr("broker.factory.get_gateway", gateway_factory)
        decision = ExecutionPolicy.evaluate(_intent(), _context())
        assert decision.allowed is True
        gateway_factory.assert_not_called()


class TestCompleteRejectionPrecedence:
    """Each earlier check wins when the immediately following check also fails."""

    @pytest.mark.parametrize(
        "intent,context,expected",
        [
            (
                _intent(risk_approved=False),
                _context(emergency_stop=True),
                ExecutionDecisionCode.EMERGENCY_STOP,
            ),
            (
                _intent(risk_approved=False),
                None,
                ExecutionDecisionCode.RISK_NOT_APPROVED,
            ),
            (
                _intent(side="HOLD"),
                None,
                ExecutionDecisionCode.SAFETY_CONTEXT_MISSING,
            ),
            (
                _intent(side="HOLD", volume=0),
                _context(),
                ExecutionDecisionCode.INVALID_DIRECTION,
            ),
            (
                _intent(volume=0, entry=0),
                _context(),
                ExecutionDecisionCode.INVALID_VOLUME,
            ),
            (
                _intent(entry=0),
                _context(daily_loss_percent=3.0),
                ExecutionDecisionCode.INVALID_PRICE_LEVELS,
            ),
            (
                _intent(),
                _context(daily_loss_percent=3.0, daily_trade_count=5),
                ExecutionDecisionCode.DAILY_LOSS_LIMIT,
            ),
            (
                _intent(),
                _context(
                    daily_trade_count=5,
                    open_positions=tuple(_position(f"EURUSD-{index}") for index in range(3)),
                ),
                ExecutionDecisionCode.DAILY_TRADE_LIMIT,
            ),
            (
                _intent(),
                _context(
                    open_positions=(
                        _position("XAUUSD"),
                        _position("EURUSD"),
                        _position("GBPUSD"),
                    )
                ),
                ExecutionDecisionCode.MAX_OPEN_POSITIONS,
            ),
            (
                _intent(),
                _context(
                    open_positions=(_position("XAUUSD"),),
                    used_idempotency_keys=frozenset({"intent-001"}),
                ),
                ExecutionDecisionCode.DUPLICATE_SYMBOL_POSITION,
            ),
        ],
    )
    def test_documented_precedence_pairwise(
        self,
        intent: ExecutionIntent,
        context: ExecutionContext | None,
        expected: ExecutionDecisionCode,
    ) -> None:
        assert _code(intent, context) is expected
