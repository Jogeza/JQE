"""
JQE Market Regime Engine

Identifies current market condition.
"""


from core.logger import logger



def detect_regime(df):

    """
    Detect market state from indicators.
    """

    latest = df.iloc[-1]


    close = latest["close"]

    ema50 = latest["EMA50"]

    ema200 = latest["EMA200"]

    rsi = latest["RSI"]

    atr = latest["ATR"]



    regime = "NO_TRADE"



    # Bullish trend

    if (
        close > ema50
        and ema50 > ema200
        and rsi > 50
    ):

        regime = "TREND_UP"



    # Bearish trend

    elif (

        close < ema50
        and ema50 < ema200
        and rsi < 50

    ):

        regime = "TREND_DOWN"



    # Range condition

    elif (

        abs(ema50 - ema200)
        < atr * 0.5

    ):

        regime = "RANGE"



    logger.info(

        f"Market regime detected: {regime}"

    )


    return regime