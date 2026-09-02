"""
JQE Institutional Performance Analytics
Version 0.1.0
"""


def calculate_performance(trades, equity_curve):

    report = {}


    total_trades = len(trades)


    wins = [
        t for t in trades
        if t["profit"] > 0
    ]


    losses = [
        t for t in trades
        if t["profit"] < 0
    ]


    report["Total Trades"] = total_trades


    report["Winning Trades"] = len(wins)

    report["Losing Trades"] = len(losses)



    if total_trades > 0:

        report["Win Rate %"] = round(
            len(wins) /
            total_trades *
            100,
            2
        )

    else:

        report["Win Rate %"] = 0



    gross_profit = sum(
        t["profit"]
        for t in wins
    )


    gross_loss = abs(
        sum(
            t["profit"]
            for t in losses
        )
    )


    if gross_loss:

        report["Profit Factor"] = round(
            gross_profit /
            gross_loss,
            2
        )

    else:

        report["Profit Factor"] = 0



    # Average trade

    if total_trades:

        report["Average Trade"] = round(
            sum(
                t["profit"]
                for t in trades
            )
            /
            total_trades,
            2
        )



    # Maximum drawdown


    peak = equity_curve[0]

    max_drawdown = 0


    for value in equity_curve:


        if value > peak:

            peak = value


        drawdown = peak - value


        if drawdown > max_drawdown:

            max_drawdown = drawdown



    report["Maximum Drawdown"] = round(
        max_drawdown,
        2
    )

    report["Gross Profit"] = round(gross_profit, 2)
    report["Gross Loss"] = round(gross_loss, 2)
    report["Net P&L"] = round(gross_profit - gross_loss, 2)
    report["Average Win"] = round(gross_profit / len(wins), 2) if wins else 0
    report["Average Loss"] = round(gross_loss / len(losses), 2) if losses else 0
    report["Expectancy"] = round((gross_profit - gross_loss) / total_trades, 2) if total_trades else 0
    report["Starting Balance"] = round(equity_curve[0], 2) if equity_curve else 0
    report["Ending Balance"] = round(equity_curve[-1], 2) if equity_curve else 0
    durations = [t["duration_candles"] for t in trades if "duration_candles" in t]
    if durations:
        report["Average Trade Duration (candles)"] = round(sum(durations) / len(durations), 2)

    win_streak = loss_streak = max_win_streak = max_loss_streak = 0
    for trade in trades:
        if trade["profit"] > 0:
            win_streak += 1
            loss_streak = 0
        elif trade["profit"] < 0:
            loss_streak += 1
            win_streak = 0
        else:
            win_streak = loss_streak = 0
        max_win_streak = max(max_win_streak, win_streak)
        max_loss_streak = max(max_loss_streak, loss_streak)
    report["Maximum Consecutive Wins"] = max_win_streak
    report["Maximum Consecutive Losses"] = max_loss_streak


    return report
