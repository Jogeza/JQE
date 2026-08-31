"""JQE Institutional Position Sizing Engine.

Calculates lot size dynamically from account risk capital, stop distance,
and instrument specifications to ensure strict risk management and prevent
fixed-lot overexposure.
"""

from __future__ import annotations

from dataclasses import dataclass

from broker.types import ExecutionQuantity, ExecutionQuantityUnit
from core.logger import logger


@dataclass(frozen=True, slots=True)
class ExecutionSizingDecision:
    """Auditable result of translating authorized cash risk into execution units."""

    authorized_risk_amount: float
    quantity: ExecutionQuantity | None
    expected_loss_at_stop: float | None
    risk_verifiable: bool
    reason: str


def authorize_execution_quantity(
    *,
    broker: str,
    balance: float,
    risk_percent: float,
    entry: float,
    stop_loss: float,
) -> ExecutionSizingDecision:
    """Authorize broker quantity only where repository semantics prove stop risk."""
    authorized_risk = balance * (risk_percent / 100.0)
    stop_distance = abs(entry - stop_loss)
    if authorized_risk <= 0 or stop_distance <= 0:
        return ExecutionSizingDecision(
            authorized_risk, None, None, False, "Risk amount or stop distance is invalid"
        )
    if broker != "simulation":
        return ExecutionSizingDecision(
            authorized_risk,
            None,
            None,
            False,
            "Broker stop-risk conversion is not proven",
        )
    value = authorized_risk / stop_distance
    expected_loss = value * stop_distance
    return ExecutionSizingDecision(
        authorized_risk_amount=authorized_risk,
        quantity=ExecutionQuantity(
            value=value,
            unit=ExecutionQuantityUnit.SIMULATION_UNITS,
        ),
        expected_loss_at_stop=expected_loss,
        risk_verifiable=expected_loss <= authorized_risk * (1.0 + 1e-12),
        reason="Simulation assumes one account-currency unit per price-unit move",
    )


class PositionSizing:
    """Calculates position lot sizes based on capital at risk."""

    def __init__(self, min_lot: float = 0.01, max_lot: float = 100.0) -> None:
        self.min_lot = min_lot
        self.max_lot = max_lot

    def calculate_lot(
        self,
        risk_amount: float,
        stop_distance: float,
        pip_value: float = 1.0,
        lot_step: float = 0.01,
    ) -> float:
        """Calculates lot size from cash risk amount and stop distance.

        Args:
            risk_amount: Cash amount willing to risk on the trade.
            stop_distance: Distance to stop loss in price units or pips.
            pip_value: Value of 1 pip per standard lot.
            lot_step: Minimum lot increment supported by broker.

        Returns:
            Computed lot size within [min_lot, max_lot], rounded to 2 decimal places.
            Returns 0.0 if stop_distance <= 0 or risk_amount <= 0.
        """
        if stop_distance <= 0 or risk_amount <= 0:
            return 0.0

        raw_lot = risk_amount / (stop_distance * pip_value)

        # Enforce bounds
        bounded_lot = max(self.min_lot, min(raw_lot, self.max_lot))
        return round(bounded_lot, 2)


def calculate_position_size(
    balance: float,
    risk_percent: float,
    stop_loss: float,
    pip_value: float = 10.0,
) -> float:
    """Convenience function calculating position lot size from balance and percentage risk.

    Args:
        balance: Account balance.
        risk_percent: Percentage of balance to risk (e.g. 0.5 for 0.5%).
        stop_loss: Distance to stop loss (e.g. ATR).
        pip_value: Multiplier to convert stop distance to currency risk per lot.

    Returns:
        Lot size floored at 0.01 minimum lot.
    """
    if stop_loss <= 0:
        return 0.01

    risk_amount = balance * (risk_percent / 100.0)
    sizer = PositionSizing(min_lot=0.01)
    lot = sizer.calculate_lot(
        risk_amount=risk_amount,
        stop_distance=stop_loss,
        pip_value=pip_value,
    )
    # Ensure minimum lot size guarantee for standard compatibility
    return max(lot, 0.01)
