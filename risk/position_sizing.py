"""Canonical execution authorization plus legacy backtesting lot helpers.

Calculates lot size dynamically from account risk capital, stop distance,
and instrument specifications to ensure strict risk management and prevent
fixed-lot overexposure.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from broker.deriv_contract_spec import (
    current_deriv_multiplier_specification,
    evaluate_deriv_quantity_capability,
)
from broker.types import ExecutionQuantity, ExecutionQuantityUnit
from core.logger import logger
from risk.simulation_contract import (
    authoritative_simulation_registry,
    canonical_simulation_proof,
    canonical_simulation_specification,
    evaluate_simulation_capability,
    floor_synthetic_quantity_exact,
)


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
    authorized_risk_decimal = (
        Decimal(str(balance)) * Decimal(str(risk_percent)) / Decimal("100")
    )
    stop_distance_decimal = abs(Decimal(str(entry)) - Decimal(str(stop_loss)))
    authorized_risk = float(authorized_risk_decimal)
    stop_distance = float(stop_distance_decimal)
    if authorized_risk <= 0 or stop_distance <= 0:
        return ExecutionSizingDecision(
            authorized_risk, None, None, False, "Risk amount or stop distance is invalid"
        )
    if broker == "deriv":
        capability = evaluate_deriv_quantity_capability(
            current_deriv_multiplier_specification()
        )
        return ExecutionSizingDecision(
            authorized_risk, None, None, False, capability.reason
        )
    if broker != "simulation":
        return ExecutionSizingDecision(
            authorized_risk,
            None,
            None,
            False,
            "Broker stop-risk conversion is not proven",
        )
    specification = canonical_simulation_specification(stop_distance_decimal)
    capability = evaluate_simulation_capability(
        specification, canonical_simulation_proof(), authoritative_simulation_registry()
    )
    if not capability.stop_risk_authorizable:
        return ExecutionSizingDecision(authorized_risk, None, None, False, capability.reason)
    quantity_decimal = floor_synthetic_quantity_exact(
        authorized_risk_decimal, specification
    )
    if quantity_decimal is None:
        return ExecutionSizingDecision(
            authorized_risk, None, None, False,
            "Authorized risk is below the synthetic minimum quantity",
        )
    expected_loss_decimal = quantity_decimal * stop_distance_decimal
    if expected_loss_decimal > authorized_risk_decimal:
        return ExecutionSizingDecision(
            authorized_risk, None, None, False,
            "Synthetic quantity exceeds the exact authorized risk",
        )

    # ExecutionQuantity and audit fields currently store floats. Conversion is
    # an output boundary only; it does not participate in authorization.
    value = float(quantity_decimal)
    expected_loss = float(expected_loss_decimal)
    return ExecutionSizingDecision(
        authorized_risk_amount=authorized_risk,
        quantity=ExecutionQuantity(
            value=value,
            unit=ExecutionQuantityUnit.SIMULATION_UNITS,
        ),
        expected_loss_at_stop=expected_loss,
        risk_verifiable=True,
        reason="JQE synthetic simulation proof verifies linear stop risk",
    )


class PositionSizing:
    """Noncanonical lot calculator retained for backtesting compatibility only.

    Its float output must never be passed to ``ExecutionIntent`` or
    ``OrderRequest``. Broker-bound sizing uses ``authorize_execution_quantity``.
    """

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
    """Calculate a noncanonical backtesting lot value.

    This compatibility helper is not an execution authorization and its raw
    float result must never cross a broker request boundary.

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
