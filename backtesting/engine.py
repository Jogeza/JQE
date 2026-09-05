"""Chronological, single-position deterministic backtest engine."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import pandas as pd

from backtesting.models import BacktestDecision, BacktestExecutionAssumptions, BacktestExitReason, BacktestRiskConfiguration, BacktestTrade, BacktestResult
from broker.types import ExecutionQuantity, ExecutionQuantityUnit, Timeframe
from risk.risk_engine import RiskEngine
from execution.simulator import calculate_stop_target


@dataclass(slots=True)
class _PendingSignal:
    direction: str
    confidence: int
    signal_index: int
    atr: float


@dataclass(slots=True)
class _OpenPosition:
    direction: str
    signal_index: int
    entry_index: int
    entry_price: float
    stop: float
    target: float
    quantity: ExecutionQuantity
    balance_before: float


class BacktestEngine:
    """Event-driven research engine; balance changes only at reached exits."""
    def __init__(self, starting_balance: float = 50.0, *, symbol: str = "XAUUSD", timeframe: Timeframe = Timeframe.M5, risk: BacktestRiskConfiguration | None = None, execution: BacktestExecutionAssumptions | None = None) -> None:
        if starting_balance <= 0:
            raise ValueError("starting_balance must be positive")
        self.starting_balance = self.balance = float(starting_balance)
        self.symbol, self.timeframe = symbol, timeframe
        self.risk_configuration = risk or BacktestRiskConfiguration()
        self.execution_assumptions = execution or BacktestExecutionAssumptions()
        self._risk_engine = RiskEngine(min_confidence=self.risk_configuration.minimum_confidence, max_risk_percent=self.risk_configuration.risk_percent)
        self._pending: _PendingSignal | None = None
        self._position: _OpenPosition | None = None
        self.trades: list[BacktestTrade] = []
        self.decisions: list[BacktestDecision] = []
        self.equity_curve: list[float] = [self.balance]
        self.total_trades = self.wins = self.losses = 0
        self.result: BacktestResult | None = None

    def process_candle(self, index: int, dataframe: pd.DataFrame) -> None:
        row = dataframe.iloc[index]
        if (
            self._position is None
            and self._pending is not None
            and index > self._pending.signal_index
        ):
            self._enter(index, row)
            self._pending = None
        if self._position is not None:
            self._evaluate_exit(index, row, dataframe)

    def queue_signal(self, signal: dict[str, Any], index: int, dataframe: pd.DataFrame) -> None:
        direction, confidence = signal.get("signal"), int(signal.get("confidence", 0))
        atr = float(dataframe.iloc[index].get("ATR", 0.0))
        state = "NO_TRADE"
        reasons = [str(reason) for reason in signal.get("reasons", [])]
        if self._position is not None:
            state, reasons = "REJECTED_CANDIDATE", [*reasons, "Position already open"]
        elif self._pending is not None:
            state, reasons = "REJECTED_CANDIDATE", [*reasons, "Entry already pending"]
        elif direction not in ("BUY", "SELL"):
            state = "NO_TRADE"
        elif confidence < self.risk_configuration.minimum_confidence:
            state, reasons = "REJECTED_CANDIDATE", [*reasons, "Confidence below backtest minimum"]
        elif atr <= 0:
            state, reasons = "INSUFFICIENT_SETUP", [*reasons, "ATR unavailable"]
        else:
            decision = self._risk_engine.approve_trade(signal, dataframe.iloc[: index + 1], balance=self.balance, enforce_limits=False)
            if decision["approved"]:
                self._pending = _PendingSignal(direction, confidence, index, atr)
                state = "QUEUED"
            else:
                state = "RISK_BLOCKED"
                reason = decision.get("reason") or decision.get("rejection_reason")
                if reason:
                    reasons.append(str(reason))
        plan = signal.get("trade_plan")
        self.decisions.append(BacktestDecision(
            candle_index=index,
            timestamp=dataframe.iloc[index]["time"],
            signal=str(direction or "NO_TRADE"),
            confidence=confidence,
            state=state,
            reasons=tuple(reasons),
            entry_price=getattr(plan, "entry", None),
            stop_price=getattr(plan, "stop_loss", None),
            target_price=getattr(plan, "take_profit", None),
        ))
        if state != "QUEUED":
            return

    def finish(self, final_index: int, dataframe: pd.DataFrame) -> None:
        if self._position is not None:
            self._close(final_index, float(dataframe.iloc[final_index]["close"]), BacktestExitReason.END_OF_DATA, dataframe)
        self._pending = None

    def execute_trade(self, signal: dict[str, Any], current_index: int, dataframe: pd.DataFrame) -> dict[str, Any] | None:
        """Compatibility shim for legacy unit callers.

        New backtests must use ``process_candle`` and ``queue_signal``. This
        method retains the former immediate test helper without being used by
        the canonical runner.
        """
        direction = signal.get("signal")
        if direction not in ("BUY", "SELL"):
            return None
        row = dataframe.iloc[current_index]
        atr = float(row.get("ATR", 0.0))
        decision = self._risk_engine.approve_trade(signal, dataframe.iloc[: current_index + 1], balance=self.balance)
        if not decision["approved"] or atr <= 0:
            return None
        entry = float(row["close"])
        stop, target = calculate_stop_target(entry, atr, direction)
        future = dataframe.iloc[current_index + 1: current_index + 20]
        result = None
        for exit_index, candle in future.iterrows():
            if (direction == "BUY" and float(candle["low"]) <= stop) or (direction == "SELL" and float(candle["high"]) >= stop):
                result = {"profit": -1, "result": "LOSS", "entry": entry, "exit": stop, "entry_index": current_index, "exit_index": exit_index}
                break
            if (direction == "BUY" and float(candle["high"]) >= target) or (direction == "SELL" and float(candle["low"]) <= target):
                result = {"profit": 3, "result": "WIN", "entry": entry, "exit": target, "entry_index": current_index, "exit_index": exit_index}
                break
        if result is None:
            exit_index = future.index[-1] if not future.empty else current_index
            result = {"profit": 0, "result": "TIMEOUT", "entry": entry, "exit": float(dataframe.loc[exit_index, "close"]), "entry_index": current_index, "exit_index": exit_index}
        profit = float(result["profit"])
        before = self.balance
        self.balance += profit
        self.total_trades += 1
        self.wins += int(profit > 0)
        self.losses += int(profit < 0)
        timestamp = row.get("time", pd.Timestamp("1970-01-01", tz="UTC"))
        exit_timestamp = dataframe.loc[result["exit_index"]].get("time", timestamp)
        quantity = ExecutionQuantity(value=1.0, unit=ExecutionQuantityUnit.SIMULATION_UNITS)
        self.trades.append(BacktestTrade(len(self.trades) + 1, self.symbol, self.timeframe, direction, timestamp, timestamp, entry, exit_timestamp, float(result["exit"]), stop, target, quantity, profit, 0.0, profit, before, self.balance, int(result["exit_index"] - current_index), BacktestExitReason.TAKE_PROFIT if profit > 0 else BacktestExitReason.STOP_LOSS if profit < 0 else BacktestExitReason.TIMEOUT))
        self.equity_curve.append(self.balance)
        return result

    def _enter(self, index: int, row: pd.Series) -> None:
        assert self._pending is not None
        adverse = self.execution_assumptions.spread + self.execution_assumptions.slippage
        raw_open = float(row["open"])
        entry = raw_open + adverse if self._pending.direction == "BUY" else raw_open - adverse
        stop_distance = self._pending.atr * 1.5
        risk_amount = self.balance * self.risk_configuration.risk_percent / 100.0
        if stop_distance <= 0 or risk_amount <= self.execution_assumptions.fee_per_trade or risk_amount > self.balance:
            return
        quantity = ExecutionQuantity(value=risk_amount / stop_distance, unit=ExecutionQuantityUnit.SIMULATION_UNITS)
        if self._pending.direction == "BUY":
            stop, target = entry - stop_distance, entry + self._pending.atr * 3.0
        else:
            stop, target = entry + stop_distance, entry - self._pending.atr * 3.0
        self._position = _OpenPosition(self._pending.direction, self._pending.signal_index, index, entry, stop, target, quantity, self.balance)

    def _evaluate_exit(self, index: int, row: pd.Series, dataframe: pd.DataFrame) -> None:
        assert self._position is not None
        p = self._position
        if p.direction == "BUY":
            stop_hit, target_hit = float(row["low"]) <= p.stop, float(row["high"]) >= p.target
        else:
            stop_hit, target_hit = float(row["high"]) >= p.stop, float(row["low"]) <= p.target
        if stop_hit:
            self._close(index, p.stop, BacktestExitReason.STOP_LOSS, dataframe)
        elif target_hit:
            self._close(index, p.target, BacktestExitReason.TAKE_PROFIT, dataframe)
        elif index - p.entry_index + 1 >= self.execution_assumptions.max_holding_candles:
            self._close(index, float(row["close"]), BacktestExitReason.TIMEOUT, dataframe)

    def _close(self, index: int, exit_price: float, reason: BacktestExitReason, dataframe: pd.DataFrame) -> None:
        assert self._position is not None
        p = self._position
        gross = ((exit_price - p.entry_price) if p.direction == "BUY" else (p.entry_price - exit_price)) * p.quantity.value
        costs, before = self.execution_assumptions.fee_per_trade, p.balance_before
        net = gross - costs
        self.balance += net
        self.trades.append(BacktestTrade(len(self.trades) + 1, self.symbol, self.timeframe, p.direction, dataframe.iloc[p.signal_index]["time"], dataframe.iloc[p.entry_index]["time"], p.entry_price, dataframe.iloc[index]["time"], exit_price, p.stop, p.target, p.quantity, gross, costs, net, before, self.balance, index - p.entry_index + 1, reason))
        self.equity_curve.append(self.balance)
        self.total_trades += 1
        self.wins += int(net > 0)
        self.losses += int(net < 0)
        self._position = None

    def statistics(self) -> dict[str, float | int]:
        return {"Starting Balance": self.starting_balance, "Ending Balance": round(self.balance, 2), "Net Profit": round(self.balance - self.starting_balance, 2), "Trades": self.total_trades, "Wins": self.wins, "Losses": self.losses}
