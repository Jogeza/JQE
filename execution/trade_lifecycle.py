"""JQE Trade Lifecycle Processor.

Validates risk approval, creates an order, and opens a position.

**Direction contract (strictly enforced):**

    BUY:   stop_loss < entry < take_profit
    SELL:  take_profit < entry < stop_loss

The *caller* is responsible for computing ``stop_loss`` and
``take_profit`` via :mod:`risk.risk_manager` or
:func:`execution.simulator.calculate_stop_target` before calling
:meth:`TradeLifecycle.process`.  This class validates that the supplied
levels satisfy the directional invariant and rejects the trade if they
do not — it does **not** fabricate levels itself.

Previous behaviour (hardcoded ``price ± 10``/``price ± 20``) was
incorrect for SELL trades because it placed the stop *below* entry and
the target *above* entry, which is the BUY convention.  That code has
been removed and replaced with explicit caller-supplied levels +
invariant validation.
"""

from __future__ import annotations


class TradeLifecycle:
    """Validates risk, creates an order, and opens a position."""

    def process(
        self,
        signal: str,
        risk: dict,
        order_manager,
        position_manager,
        symbol: str,
        price: float,
        stop_loss: float | None = None,
        take_profit: float | None = None,
        lot: float = 0.01,
    ) -> dict:
        """Processes a trade through validation → order → position.

        Args:
            signal: ``"BUY"`` or ``"SELL"``.
            risk: Risk dict; must have a positive ``"risk_percent"`` key
                for the trade to be approved.
            order_manager: Provides :meth:`create_order`.
            position_manager: Provides :meth:`open_position`.
            symbol: Instrument symbol.
            price: Entry price.
            stop_loss: Caller-supplied stop-loss price.
                BUY: must be *below* ``price``.
                SELL: must be *above* ``price``.
                If ``None``, the trade is rejected with an explanation.
            take_profit: Caller-supplied take-profit price.
                BUY: must be *above* ``price``.
                SELL: must be *below* ``price``.
                If ``None``, the trade is rejected with an explanation.
            lot: Lot size (default 0.01 — override from the risk engine).

        Returns:
            ``{"status": "EXECUTED", "position": ...}`` on success, or
            ``{"status": "REJECTED", "reason": "..."}`` on any failure.
        """
        # ------------------------------------------------------------------
        # Risk approval
        # ------------------------------------------------------------------
        if risk.get("risk_percent", 0) <= 0:
            return {"status": "REJECTED", "reason": "Risk denied"}

        # ------------------------------------------------------------------
        # Require explicit SL/TP — we never fabricate levels
        # ------------------------------------------------------------------
        if stop_loss is None:
            return {"status": "REJECTED", "reason": "Missing stop_loss"}
        if take_profit is None:
            return {"status": "REJECTED", "reason": "Missing take_profit"}

        # ------------------------------------------------------------------
        # Directional invariant — hard reject on violation
        # ------------------------------------------------------------------
        if signal == "BUY":
            if stop_loss >= price:
                return {
                    "status": "REJECTED",
                    "reason": (
                        f"BUY invariant violated: stop_loss ({stop_loss}) "
                        f"must be < entry ({price})"
                    ),
                }
            if take_profit <= price:
                return {
                    "status": "REJECTED",
                    "reason": (
                        f"BUY invariant violated: take_profit ({take_profit}) "
                        f"must be > entry ({price})"
                    ),
                }
        elif signal == "SELL":
            if stop_loss <= price:
                return {
                    "status": "REJECTED",
                    "reason": (
                        f"SELL invariant violated: stop_loss ({stop_loss}) "
                        f"must be > entry ({price})"
                    ),
                }
            if take_profit >= price:
                return {
                    "status": "REJECTED",
                    "reason": (
                        f"SELL invariant violated: take_profit ({take_profit}) "
                        f"must be < entry ({price})"
                    ),
                }
        else:
            return {"status": "REJECTED", "reason": f"Unknown signal: {signal!r}"}

        # ------------------------------------------------------------------
        # Create order
        # ------------------------------------------------------------------
        order = order_manager.create_order(
            signal,
            symbol,
            lot=lot,
            entry=price,
            stop_loss=stop_loss,
            take_profit=take_profit,
        )

        if order.get("status") == "REJECTED":
            return order

        # ------------------------------------------------------------------
        # Open position
        # ------------------------------------------------------------------
        position = position_manager.open_position(order)

        return {"status": "EXECUTED", "position": position}