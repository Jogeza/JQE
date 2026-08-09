from __future__ import annotations

import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class TradePlan(BaseModel):
    """Canonical model for a trading setup decision and execution plan.
    
    A TradePlan explicitly separates market intelligence (trend/momentum/regime)
    from signal (BUY/SELL) and risk parameters (entry/stop_loss/take_profit).
    It guarantees that if a signal is valid, the corresponding safety checks
    and invariants (e.g. BUY: SL < entry < TP) are satisfied.
    """
    
    symbol: str

    # Signal & Confidence
    signal: Literal["BUY", "SELL", "NO_TRADE"]
    confidence: int = Field(default=0, ge=0, le=100)
    quality: str = Field(default="POOR")
    score: int = Field(default=0)
    setup_type: str = Field(default="NO_SETUP")

    # Entry & Targets
    entry_type: Optional[str] = Field(default=None)
    entry: Optional[float] = Field(default=None)
    
    stop_method: Optional[str] = Field(default=None)
    stop_loss: Optional[float] = Field(default=None)
    
    target_rr: Optional[float] = Field(default=None)
    take_profit: Optional[float] = Field(default=None)
    risk_reward: Optional[float] = Field(default=None)

    # Risk & Sizing
    position_size: Optional[float] = Field(default=None)
    risk_percent: Optional[float] = Field(default=None)
    risk_amount: Optional[float] = Field(default=None)

    # Market Intelligence Context
    atr: Optional[float] = Field(default=None)
    trend: str = Field(default="UNKNOWN")
    momentum: str = Field(default="UNKNOWN")
    volatility: str = Field(default="UNKNOWN")
    liquidity: str = Field(default="UNKNOWN")
    regime: str = Field(default="UNKNOWN")

    # Context & Auditability
    reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    invalidation: Optional[str] = Field(default=None)
    generated_at: str = Field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())

    def is_valid(self) -> bool:
        """Returns whether this TradePlan is a valid, actionable trade."""
        if self.signal == "NO_TRADE":
            return False
        if self.entry is None or self.stop_loss is None or self.take_profit is None:
            return False
        
        # Enforce direction invariants
        if self.signal == "BUY":
            if not (self.stop_loss < self.entry < self.take_profit):
                return False
        elif self.signal == "SELL":
            if not (self.take_profit < self.entry < self.stop_loss):
                return False
                
        # Enforce Minimum RR if risk/reward is present
        # Default minimum is 1.5, per guidelines.
        if self.risk_reward is not None and self.risk_reward < 1.5:
            return False
            
        return True


class TradePlanBuilder:
    """Constructs TradePlans from market intelligence and signal decisions."""

    def __init__(self, min_rr: float = 1.5, atr_sl_multiplier: float = 1.5, target_rr: float = 2.0):
        """Initializes the builder with strategy risk policies.
        
        Args:
            min_rr: The minimum risk-to-reward ratio allowed.
            atr_sl_multiplier: The multiple of ATR to use for stop loss distance.
            target_rr: The target risk-to-reward ratio for calculating take_profit.
        """
        self.min_rr = min_rr
        self.atr_sl_multiplier = atr_sl_multiplier
        self.target_rr = target_rr

    def _reject(
        self, 
        base_plan: dict, 
        reason: str, 
        warnings: list[str] | None = None
    ) -> TradePlan:
        """Helper to return a NO_TRADE plan with a specific rejection reason."""
        merged_warnings = base_plan.get("warnings", []) + (warnings or [])
        reasons = base_plan.get("reasons", [])
        if reason:
            reasons.append(f"Rejected: {reason}")
            
        clean_plan = {k: v for k, v in base_plan.items() if k not in ("reasons", "warnings")}
        return TradePlan(
            **clean_plan,
            signal="NO_TRADE",
            setup_type="NO_SETUP",
            reasons=reasons,
            warnings=merged_warnings,
            # Nullify execution fields
            entry_type=None,
            entry=None,
            stop_method=None,
            stop_loss=None,
            take_profit=None,
            risk_reward=None,
            position_size=None,
            risk_percent=None,
            risk_amount=None,
        )

    def build(
        self, 
        symbol: str, 
        intelligence: dict, 
        signal_dict: dict, 
        price: float, 
        account_balance: float | None = None,
        risk_percent: float = 1.0,
    ) -> TradePlan:
        """Constructs a comprehensive TradePlan.
        
        Args:
            symbol: The market symbol (e.g. BTCUSD).
            intelligence: The intelligence dictionary (trend, momentum, ATR, etc).
            signal_dict: The signal output (signal, score, reasons, etc).
            price: Current market price (ask for BUY, bid for SELL).
            account_balance: Account balance to calculate position size.
            risk_percent: The percentage of the account to risk.
            
        Returns:
            A populated TradePlan object.
        """
        atr = intelligence.get("atr", intelligence.get("ATR", intelligence.get("ATR_14")))
        
        # Base intelligence context
        base_plan = {
            "symbol": symbol,
            "confidence": signal_dict.get("confidence", 0),
            "quality": signal_dict.get("quality", "POOR"),
            "score": signal_dict.get("score", 0),
            "trend": intelligence.get("trend", "UNKNOWN"),
            "momentum": intelligence.get("momentum", "UNKNOWN"),
            "volatility": intelligence.get("volatility", "UNKNOWN"),
            "liquidity": intelligence.get("liquidity", "UNKNOWN"),
            "regime": intelligence.get("regime", "UNKNOWN"),
            "atr": atr,
            "reasons": signal_dict.get("reasons", []).copy(),
            "warnings": []
        }

        # 1. Price Gate
        if not price or price <= 0:
            return self._reject(base_plan, "Invalid or unavailable market price")

        # 2. Intelligence/Quality Gating
        warnings = []
        if base_plan["liquidity"] == "LOW":
            warnings.append("Low liquidity")
        if base_plan["volatility"] == "HIGH":
            warnings.append("High volatility")
            
        # Example of RSI warning logic (assuming RSI is passed in intelligence)
        rsi = intelligence.get("rsi", intelligence.get("RSI", intelligence.get("RSI_14")))
        if rsi is not None:
            if rsi >= 70:
                warnings.append("Elevated RSI (Overbought)")
            elif rsi <= 30:
                warnings.append("Depressed RSI (Oversold)")
                
        base_plan["warnings"] = warnings

        # 3. Base Signal Checks
        raw_signal = signal_dict.get("signal", "NO_TRADE")
        if raw_signal not in ("BUY", "SELL"):
            return self._reject(base_plan, "Signal model did not produce a valid setup")

        if not atr or atr <= 0:
            return self._reject(base_plan, "Cannot calculate ATR-based stops (Invalid ATR)")

        # 4. Entry, Stop Loss, and Take Profit
        entry = float(price)
        stop_dist = float(atr * self.atr_sl_multiplier)
        target_dist = float(atr * self.atr_sl_multiplier * self.target_rr)
        
        if raw_signal == "BUY":
            stop_loss = entry - stop_dist
            take_profit = entry + target_dist
            invalidation = f"Price closes below {round(stop_loss, 5)}"
        else: # SELL
            stop_loss = entry + stop_dist
            take_profit = entry - target_dist
            invalidation = f"Price closes above {round(stop_loss, 5)}"
            
        # 5. Risk / Reward and Minimum RR validation
        risk = abs(entry - stop_loss)
        reward = abs(entry - take_profit)
        actual_rr = reward / risk if risk > 0 else 0
        
        if actual_rr < self.min_rr:
            return self._reject(base_plan, f"Risk/reward ({round(actual_rr, 2)}) below minimum threshold ({self.min_rr})")

        # 6. Position Sizing
        pos_size = None
        risk_amount = None
        if account_balance and account_balance > 0 and risk > 0:
            risk_amount = account_balance * (risk_percent / 100.0)
            # Basic size calculation. Usually requires tick value and contract size to be robust.
            # Assuming 1 unit distance = 1 base currency for simple demo.
            pos_size = round(risk_amount / risk, 2)
            if pos_size < 0.01:
                pos_size = 0.01
        
        return TradePlan(
            **base_plan,
            signal=raw_signal,
            setup_type="TREND_CONTINUATION" if base_plan["trend"] in ("BULLISH", "BEARISH") else "UNKNOWN",
            entry_type="MARKET",
            entry=entry,
            stop_method="ATR",
            stop_loss=round(stop_loss, 5),
            target_rr=self.target_rr,
            take_profit=round(take_profit, 5),
            risk_reward=round(actual_rr, 2),
            position_size=pos_size,
            risk_percent=risk_percent if pos_size else None,
            risk_amount=round(risk_amount, 2) if risk_amount else None,
            invalidation=invalidation,
        )
