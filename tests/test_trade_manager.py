"""Focused tests for broker-position to policy-snapshot conversion."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from broker.types import OrderSide, Position
from execution.policy import PositionSnapshot
from execution.trade_manager import PositionSnapshotAdapter


def _position(**overrides: object) -> Position:
    values: dict[str, object] = {
        "position_id": "p-1",
        "symbol": " eurusd ",
        "side": OrderSide.BUY,
        "volume": 1.0,
        "open_price": 100.0,
        "opened_at": datetime.now(timezone.utc),
    }
    values.update(overrides)
    return Position(**values)


def _malformed_position(**overrides: object) -> Position:
    """Construct deliberately malformed runtime DTOs for fail-closed tests."""
    values: dict[str, object] = {
        "position_id": "p-1",
        "symbol": "EURUSD",
        "side": OrderSide.BUY,
        "volume": 1.0,
        "open_price": 100.0,
    }
    values.update(overrides)
    return Position.model_construct(**values)


def test_converts_positions_to_immutable_minimal_snapshots() -> None:
    snapshots = PositionSnapshotAdapter.from_positions([_position()])

    assert snapshots == (PositionSnapshot(symbol="eurusd", side=OrderSide.BUY),)
    assert isinstance(snapshots, tuple)


@pytest.mark.parametrize("positions", [None, [], ()])
def test_empty_or_missing_positions_are_safe(positions: object) -> None:
    assert PositionSnapshotAdapter.from_positions(positions) in (None, ())


@pytest.mark.parametrize(
    "position",
    [
        object(),
        {"symbol": "EURUSD", "side": "BUY"},
        _malformed_position(symbol="   "),
        _malformed_position(symbol=None),
        _malformed_position(side="BUY"),
        _malformed_position(side="HOLD"),
    ],
)
def test_malformed_broker_positions_fail_closed(position: object) -> None:
    assert PositionSnapshotAdapter.from_positions([position]) is None


def test_generator_failure_fails_closed() -> None:
    def broken() -> object:
        yield _position()
        raise RuntimeError("unreadable broker state")

    assert PositionSnapshotAdapter.from_positions(broken()) is None


def test_unexpected_iterator_failure_fails_closed() -> None:
    def broken() -> object:
        raise ValueError("unexpected broker failure")
        yield _position()  # pragma: no cover

    assert PositionSnapshotAdapter.from_positions(broken()) is None


def test_adapter_does_not_construct_or_call_a_gateway(monkeypatch: pytest.MonkeyPatch) -> None:
    gateway_calls: list[str] = []
    monkeypatch.setattr(
        "broker.factory.get_gateway",
        lambda: gateway_calls.append("constructed"),
    )

    assert PositionSnapshotAdapter.from_positions([_position()]) is not None
    assert gateway_calls == []
