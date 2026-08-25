"""JQE Unified Institutional Risk Engine.

Consolidates:
- Capital protection and exposure management
- Signal validation and confidence gating
- Market condition gating (ATR volatility, spread tolerance)
- Daily loss and trade count limit enforcement
- Dynamic risk percent scaling based on market regime and confidence
"""

from __future__ import annotations

from typing import Any

from config.settings import settings
from core.exceptions import RiskViolationError
from core.logger import logger
from risk.dynamic_risk import DynamicRisk
from risk.position_sizing import PositionSizing, calculate_position_size

# Institutional Default Constants
MIN_CONFIDENCE = 75
MAX_RISK_PERCENT = 0.5
MIN_ATR = 1.0
MAX_SPREAD = 30.0

_DEFAULT_BALANCE = 50.0


class RiskEngine:
    """Core institutional risk evaluator and controller."""

    def __init__(
        self,
        min_confidence: int = MIN_CONFIDENCE,
        max_risk_percent: float = MAX_RISK_PERCENT,
        min_atr: float = MIN_ATR,
        max_spread: float = MAX_SPREAD,
        max_daily_loss: float | None = None,
        max_trades_daily: int | None = None,
    ) -> None:
        self.min_confidence = min_confidence
        self.max_risk_percent = max_risk_percent
        self.min_atr = min_atr
        self.max_spread = max_spread
        self.max_daily_loss = (
            max_daily_loss if max_daily_loss is not None else settings.max_daily_loss
        )
        self.max_trades_daily = (
            max_trades_daily if max_trades_daily is not None else settings.max_trades_daily
        )
        self.dynamic_risk = DynamicRisk()
        self.position_sizer = PositionSizing()

        # Session state tracking for limits
        self._daily_trades_count = 0
        self._daily_realized_loss_percent = 0.0

    def record_trade_execution(self) -> None:
        """Records a new trade execution against daily limits."""
        self._daily_trades_count += 1

    def record_loss(self, loss_percent: float) -> None:
        """Records a realized loss percentage against daily limits."""
        self._daily_realized_loss_percent += max(0.0, loss_percent)

    def reset_daily_stats(self) -> None:
        """Resets daily tracking counters for a new trading day."""
        self._daily_trades_count = 0
        self._daily_realized_loss_percent = 0.0

    def reconcile_daily_history(self, trades: list[Any], balance: float) -> None:
        """Rebuilds daily state statelessly from the broker's closed-trade history.

        Args:
            trades: A list of broker.types.TradeHistoryEntry objects.
            balance: The current account balance to compute loss percentages.
        """
        from datetime import datetime, timezone

        self.reset_daily_stats()
        today = datetime.now(timezone.utc).date()

        for trade in trades:
            if getattr(trade, "closed_at").date() == today:
                self.record_trade_execution()

                profit = getattr(trade, "profit", 0.0)
                if profit < 0:
                    loss_percent = (abs(profit) / balance) * 100
                    self.record_loss(loss_percent)

    def evaluate_limits(self) -> tuple[bool, str]:
        """Checks daily exposure and trade frequency limits.

        Returns:
            Tuple of (is_allowed, reason).
        """
        if self._daily_trades_count >= self.max_trades_daily:
            return False, f"Daily trade limit reached ({self.max_trades_daily})"

        if self._daily_realized_loss_percent >= self.max_daily_loss:
            return False, f"Daily maximum loss limit reached ({self.max_daily_loss}%)"

        return True, "Limits OK"

    def approve_trade(
        self,
        signal: dict[str, Any] | None,
        market_data: Any,
        balance: float = _DEFAULT_BALANCE,
        enforce_limits: bool = False,
    ) -> dict[str, Any]:
        """Evaluates a proposed trade signal against institutional risk standards.

        Args:
            signal: Signal dictionary containing 'signal' and 'confidence'.
            market_data: Market DataFrame or Series containing 'ATR' and optional 'spread'.
            balance: Account balance for position sizing.
            enforce_limits: Whether to check stateful daily limits.

        Returns:
            Dictionary with 'approved', 'reason', 'risk_percent', 'lot_size'.
        """
        decision: dict[str, Any] = {
            "approved": False,
            "reason": "",
            "risk_percent": 0.0,
            "lot_size": 0.0,
        }

        # 1. Signal presence check
        if signal is None:
            decision["reason"] = "Missing signal"
            return decision

        direction = signal.get("signal")
        if direction not in ("BUY", "SELL"):
            decision["reason"] = "No trade signal"
            return decision

        # 2. Confidence filter
        confidence = signal.get("confidence", 0)
        if confidence < self.min_confidence:
            decision["reason"] = "Confidence too low"
            return decision

        # 3. Optional daily limits
        if enforce_limits:
            limits_ok, limit_reason = self.evaluate_limits()
            if not limits_ok:
                decision["reason"] = limit_reason
                return decision

        # 4. Market validation
        try:
            candle = market_data.iloc[-1]
        except (AttributeError, IndexError, TypeError):
            decision["reason"] = "Invalid market data"
            return decision

        atr = candle.get("ATR", 0)
        if atr < self.min_atr:
            decision["reason"] = "Low volatility"
            return decision

        spread = candle.get("spread", 0)
        if spread > self.max_spread:
            decision["reason"] = "Spread too high"
            return decision

        # 5. Dynamic / Institutional risk percent sizing
        risk_percent = self.max_risk_percent

        # 6. Calculate position size
        lot_size = calculate_position_size(
            balance=balance,
            risk_percent=risk_percent,
            stop_loss=atr,
        )

        decision["approved"] = True
        decision["reason"] = "Institutional risk passed"
        decision["risk_percent"] = risk_percent
        decision["lot_size"] = lot_size

        return decision
