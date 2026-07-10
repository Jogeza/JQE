"""
JQE Indicator Engine
"""


import pandas as pd



def calculate_indicators(df):


    data = df.copy()



    # Trend

    data["EMA50"] = (
        data["close"]
        .ewm(span=50)
        .mean()
    )


    data["EMA200"] = (
        data["close"]
        .ewm(span=200)
        .mean()
    )



    # RSI

    delta = (
        data["close"]
        .diff()
    )


    gain = delta.clip(
        lower=0
    )


    loss = (
        -delta.clip(
            upper=0
        )
    )


    avg_gain = (
        gain
        .rolling(14)
        .mean()
    )


    avg_loss = (
        loss
        .rolling(14)
        .mean()
    )


    rs = (
        avg_gain /
        avg_loss
    )


    data["RSI"] = (
        100 -
        (100/(1+rs))
    )



    # ATR

    high_low = (
        data["high"]
        -
        data["low"]
    )


    high_close = (
        abs(
            data["high"]
            -
            data["close"].shift()
        )
    )


    low_close = (
        abs(
            data["low"]
            -
            data["close"].shift()
        )
    )


    ranges = pd.concat(
        [
            high_low,
            high_close,
            low_close
        ],
        axis=1
    )


    true_range = ranges.max(
        axis=1
    )


    data["ATR"] = (
        true_range
        .rolling(14)
        .mean()
    )


    return data