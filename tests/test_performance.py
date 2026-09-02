from analytics.performance import calculate_performance


def test_performance_metrics_are_deterministic_and_complete() -> None:
    trades = [
        {"profit": 3.0, "duration_candles": 2},
        {"profit": -1.0, "duration_candles": 4},
        {"profit": -1.0, "duration_candles": 3},
    ]
    report = calculate_performance(trades, [50.0, 53.0, 52.0, 51.0])
    assert report == calculate_performance(trades, [50.0, 53.0, 52.0, 51.0])
    assert report["Total Trades"] == 3
    assert report["Gross Profit"] == 3.0
    assert report["Gross Loss"] == 2.0
    assert report["Net P&L"] == 1.0
    assert report["Maximum Drawdown"] == 2.0
    assert report["Profit Factor"] == 1.5
    assert report["Expectancy"] == 0.33
    assert report["Starting Balance"] == 50.0
    assert report["Ending Balance"] == 51.0
    assert report["Maximum Consecutive Losses"] == 2
