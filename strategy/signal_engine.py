"""
JQE Signal Intelligence Engine

Creates trade decisions using:
- Market regime
- Trend
- Momentum
- Volatility
"""


from core.logger import logger



def generate_signal(df, regime):

    """
    Generate a professional trade signal.
    """

    latest = df.iloc[-1]


    close = latest["close"]

    ema50 = latest["EMA50"]

    ema200 = latest["EMA200"]

    rsi = latest["RSI"]

    atr = latest["ATR"]



    score = 0

    reasons = []



    signal = "NO_TRADE"



    # =====================
    # MARKET REGIME FILTER
    # =====================


    if regime == "TREND_UP":

        score += 30

        reasons.append(
            "Bullish market regime"
        )



    elif regime == "TREND_DOWN":

        score += 30

        reasons.append(
            "Bearish market regime"
        )



    else:

        logger.info(
            "Market not suitable for trading"
        )

        return {

            "signal": "NO_TRADE",

            "confidence": 0,

            "reason": [
                "No clear trend"
            ]

        }



    # =====================
    # TREND CONFIRMATION
    # =====================


    if close > ema50 > ema200:

        score += 25

        reasons.append(
            "EMA bullish alignment"
        )



    elif close < ema50 < ema200:

        score += 25

        reasons.append(
            "EMA bearish alignment"
        )



    # =====================
    # MOMENTUM
    # =====================


    if 50 < rsi < 70:

        score += 20

        reasons.append(
            "Healthy bullish momentum"
        )



    elif 30 < rsi < 50:

        score += 20

        reasons.append(
            "Healthy bearish momentum"
        )



    # =====================
    # VOLATILITY CHECK
    # =====================


    if atr > 1:

        score += 15

        reasons.append(
            "Sufficient volatility"
        )



    # =====================
    # FINAL DECISION
    # =====================


    if score >= 70:


        if regime == "TREND_UP":

            signal = "BUY"



        elif regime == "TREND_DOWN":

            signal = "SELL"



    logger.info(

        f"Signal: {signal} Confidence: {score}"

    )



    return {

        "signal": signal,

        "confidence": score,

        "reason": reasons

    }