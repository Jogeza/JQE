from types import SimpleNamespace

from research.performance_experiments import performance_metrics


def test_performance_metrics_directional_accounting():
    result = SimpleNamespace(
        trades=[], decisions=[], initial_capital=50.0, ending_capital=50.0,
        absolute_pnl=0.0, return_percent=0.0, maximum_drawdown_percent=0.0,
        winning_trades=0, losing_trades=0, win_rate_percent=0.0,
        gross_profit=0.0, gross_loss=0.0, profit_factor=None, expectancy=0.0,
        average_winner=None, average_loser=None, largest_winner=None,
        largest_loser=None, maximum_consecutive_wins=0,
        maximum_consecutive_losses=0, average_holding_candles=0.0,
    )
    metrics = performance_metrics(result)
    assert metrics["BUY"]["trades"] + metrics["SELL"]["trades"] == metrics["Actual Opened Trades"]
    assert metrics["BUY"]["net_pnl"] + metrics["SELL"]["net_pnl"] == metrics["Net P&L"]
    assert metrics["Negative Balance"] is False
