"""Independent deterministic performance experiments for frozen datasets."""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict
from statistics import median
from typing import Any, Sequence

from backtesting.models import BacktestResult


def _direction(result: BacktestResult, direction: str) -> dict[str, Any]:
    trades = [trade for trade in result.trades if trade.direction == direction]
    pnls = [trade.net_pnl for trade in trades]
    wins, losses = [x for x in pnls if x > 0], [x for x in pnls if x < 0]
    gross_profit, gross_loss = sum(wins), abs(sum(losses))
    return {
        "trades": len(trades), "wins": len(wins), "losses": len(losses),
        "win_rate_percent": len(wins)/len(trades)*100 if trades else None,
        "net_pnl": sum(pnls), "expectancy": sum(pnls)/len(trades) if trades else None,
        "profit_factor": gross_profit/gross_loss if gross_loss else None,
    }


def performance_metrics(result: BacktestResult) -> dict[str, Any]:
    trades, decisions = list(result.trades), list(result.decisions)
    durations = [trade.holding_candles for trade in trades]
    positive = sorted((trade.net_pnl for trade in trades if trade.net_pnl > 0), reverse=True)
    total_profit = sum(positive)
    losses = [trade for trade in trades if trade.net_pnl < 0]
    realized_loss_pct = [abs(trade.net_pnl)/trade.balance_before*100 for trade in losses if trade.balance_before > 0]
    theoretical_risk = [abs(trade.entry_price-trade.stop_price)*trade.quantity.value for trade in trades]
    authorized_pct = [risk/trade.balance_before*100 for risk, trade in zip(theoretical_risk, trades) if trade.balance_before > 0]
    states = Counter(decision.state for decision in decisions)
    exits = Counter(trade.exit_reason.value for trade in trades)
    raw_buy = sum(decision.signal == "BUY" for decision in decisions)
    raw_sell = sum(decision.signal == "SELL" for decision in decisions)
    balances = [result.initial_capital, *[trade.balance_after for trade in trades]]
    buy, sell = _direction(result, "BUY"), _direction(result, "SELL")
    return {
        "Starting Balance": result.initial_capital, "Ending Balance": result.ending_capital,
        "Net P&L": result.absolute_pnl, "Return %": result.return_percent,
        "Peak Balance": max(balances), "Maximum Drawdown %": result.maximum_drawdown_percent,
        "Raw BUY Signals": raw_buy, "Raw SELL Signals": raw_sell,
        "Trade Proposals": states["QUEUED"], "Authorized Trades": len(trades),
        "Risk Rejections": states["RISK_BLOCKED"], "Quantity Rejections": states["EXECUTION_REJECTED"],
        "Position State Suppressions": states["REJECTED_CANDIDATE"], "Actual Opened Trades": len(trades),
        "Winning Trades": result.winning_trades, "Losing Trades": result.losing_trades,
        "Win Rate %": result.win_rate_percent, "Gross Profit": result.gross_profit,
        "Gross Loss": result.gross_loss, "Profit Factor": result.profit_factor,
        "Expectancy": result.expectancy, "Average Winner": result.average_winner,
        "Average Loser": result.average_loser,
        "Average Win Loss Ratio": ((result.average_winner/abs(result.average_loser))
                                   if result.average_winner is not None and result.average_loser not in (None, 0) else None),
        "Largest Winner": result.largest_winner, "Largest Loser": result.largest_loser,
        "Maximum Consecutive Wins": result.maximum_consecutive_wins,
        "Maximum Consecutive Losses": result.maximum_consecutive_losses,
        "Average Trade Duration": result.average_holding_candles,
        "Median Trade Duration": median(durations) if durations else None,
        "BUY": buy, "SELL": sell, "Exit Reasons": dict(sorted(exits.items())),
        "Transaction Costs": sum(trade.costs for trade in trades),
        "Max Realized Single Trade Loss %": max(realized_loss_pct, default=None),
        "Average Realized Loss %": sum(realized_loss_pct)/len(realized_loss_pct) if realized_loss_pct else None,
        "Max Authorized Risk %": max(authorized_pct, default=None),
        "Risk Model Validation": "PASS" if all(realized <= authorized + 1e-9 for realized, authorized in zip(realized_loss_pct, [p for p,t in zip(authorized_pct,trades) if t.net_pnl < 0])) else "FAIL",
        "Fell Below 40": min(balances) < 40, "Fell Below 30": min(balances) < 30,
        "Fell Below 25": min(balances) < 25, "Fell Below 10": min(balances) < 10,
        "Negative Balance": min(balances) < 0,
        "Top 1 Profit Concentration %": (sum(positive[:1])/total_profit*100 if total_profit else None),
        "Top 5 Profit Concentration %": (sum(positive[:5])/total_profit*100 if total_profit else None),
        "Balance Curve": balances,
    }
