"""Broker-state conversion helpers for the Phase 6 execution boundary.

The adapter is deliberately read-only: it translates broker DTOs into the
small immutable state shape consumed by :mod:`execution.policy`.  It does not
connect to a gateway, submit orders, or retain a position ledger.
"""

from __future__ import annotations

from collections.abc import Iterable

from broker.types import OrderSide, Position
from execution.policy import PositionSnapshot


class PositionSnapshotAdapter:
    """Convert broker positions into policy-owned immutable snapshots."""

    @staticmethod
    def from_positions(
        positions: Iterable[object] | None,
    ) -> tuple[PositionSnapshot, ...] | None:
        """Return snapshots, or ``None`` when broker state is unreadable.

        Runtime validation is intentional here because broker responses may
        be malformed despite their declared DTO type.  Returning ``None``
        lets the caller fail closed through ``SAFETY_CONTEXT_INVALID``.
        """

        if positions is None:
            return None
        try:
            raw_positions = tuple(positions)
        except Exception:
            return None

        snapshots: list[PositionSnapshot] = []
        try:
            for position in raw_positions:
                if not isinstance(position, Position):
                    return None
                symbol = position.symbol
                side = position.side
                if (
                    not isinstance(symbol, str)
                    or not symbol.strip()
                    or not isinstance(side, OrderSide)
                    or side not in (OrderSide.BUY, OrderSide.SELL)
                ):
                    return None
                snapshots.append(PositionSnapshot(symbol=symbol.strip(), side=side))
        except Exception:
            return None

        return tuple(snapshots)
