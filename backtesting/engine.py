"""JQE Institutional Backtesting Engine."""

from __future__ import annotations

import pandas as pd

from execution.simulator import simulate_trade
from risk.risk_controller import approve_trade


class BacktestEngine:
    """Replays a signal generator's decisions over historical data.

    Attributes:
        balance: Current simulated account balance (starts at
            ``starting_balance``, updated after every closed trade).
        starting_balance: Initial simulated account balance.
        trades: Record of every trade taken.
        equity_curve: Balance after each trade, starting with
            ``starting_balance``.
        total_trades: Count of trades taken (approved and simulated,
            regardless of outcome).
        wins: Count of trades with positive profit.
        losses: Count of trades with non-positive profit.
    """

    def __init__(self, starting_balance: float = 50) -> None:
        self.balance = starting_balance
        self.starting_balance = starting_balance
        self.trades: list[dict] = []
        self.equity_curve: list[float] = [starting_balance]
        self.total_trades = 0
        self.wins = 0
        self.losses = 0

    def execute_trade(
        self, signal: dict, current_index: int, dataframe: pd.DataFrame
    ) -> dict | None:
        """Evaluates and, if approved, simulates one trade at ``current_index``.

        Args:
            signal: A signal dict with a ``"signal"`` key (``"BUY"``/
                ``"SELL"``/``"NO_TRADE"``) — see
                :func:`strategy.pipeline.generate_trading_signal`.
            current_index: Row index of the candle to evaluate/enter at.
            dataframe: Full OHLC+indicator history. Only
                ``dataframe.iloc[:current_index + 1]`` (no future data)
                is shown to the risk engine; ``simulate_trade`` is
                responsible for its own no-look-ahead guarantee on the
                execution side.

        Returns:
            The simulation result (``simulate_trade``'s return value)
            if a trade was taken, or ``None`` if the signal was
            ``"NO_TRADE"``, risk-rejected, or couldn't be simulated
            (e.g. non-positive ATR).
        """
        if signal.get("signal") == "NO_TRADE":
            return None

        market_data = dataframe.iloc[: current_index + 1]
        risk = approve_trade(signal, market_data, balance=self.balance)
        if not risk["approved"]:
            return None

        result = simulate_trade(signal, current_index, dataframe)
        if result is None:
            return None

        profit = result["profit"]
        self.balance += profit
        self.total_trades += 1
        if profit > 0:
            self.wins += 1
        else:
            self.losses += 1

        entry = dataframe.iloc[current_index]["close"]
        self.trades.append(
            {
                "type": signal["signal"],
                "profit": profit,
                "entry": result.get("entry", entry),
                "exit": result.get("exit", entry),
                "confidence": signal.get("confidence", 0),
                "lot_size": risk.get("lot_size", 0),
            }
        )
        self.equity_curve.append(self.balance)

        return result

    def statistics(self) -> dict:
        """Returns summary statistics for the backtest run so far."""
        return {
            "Starting Balance": self.starting_balance,
            "Ending Balance": round(self.balance, 2),
            "Net Profit": round(self.balance - self.starting_balance, 2),
            "Trades": self.total_trades,
            "Wins": self.wins,
            "Losses": self.losses,
        }
