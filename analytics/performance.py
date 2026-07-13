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


    return report