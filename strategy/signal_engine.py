"""
JQE Institutional Signal Engine
Version 0.1.0

Multi-factor scoring system
"""


def generate_signal(

        df,

        regime

):


    current = df.iloc[-1]


    score_buy = 0

    score_sell = 0


    reasons_buy = []

    reasons_sell = []



    # =========================
    # EMA TREND
    # =========================


    if current["EMA50"] > current["EMA200"]:


        score_buy += 25

        reasons_buy.append(

            "EMA bullish trend"

        )


    elif current["EMA50"] < current["EMA200"]:


        score_sell += 25

        reasons_sell.append(

            "EMA bearish trend"

        )





    # =========================
    # RSI MOMENTUM
    # =========================


    rsi = current["RSI"]



    if 45 < rsi < 65:


        score_buy += 20

        reasons_buy.append(

            "RSI bullish momentum"

        )



    elif 35 < rsi < 55:


        score_sell += 20

        reasons_sell.append(

            "RSI bearish momentum"

        )





    # =========================
    # ATR VOLATILITY
    # =========================


    atr = current["ATR"]



    if atr > df["ATR"].mean():


        score_buy += 15

        score_sell += 15





    # =========================
    # PRICE STRUCTURE
    # =========================


    previous = df.iloc[-2]



    if current["close"] > previous["high"]:


        score_buy += 25

        reasons_buy.append(

            "Breakout structure"

        )



    elif current["close"] < previous["low"]:


        score_sell += 25

        reasons_sell.append(

            "Breakdown structure"

        )





    # =========================
    # CANDLE POWER
    # =========================


    candle_size = abs(

        current["close"]

        -

        current["open"]

    )



    if candle_size > atr * 0.5:



        if current["close"] > current["open"]:


            score_buy += 15


            reasons_buy.append(

                "Strong bullish candle"

            )



        else:


            score_sell += 15


            reasons_sell.append(

                "Strong bearish candle"

            )







    # =========================
    # REGIME FILTER
    # =========================


    if regime == "RANGE":


        return {


            "signal":"NO_TRADE",

            "confidence":0,

            "reason":[

                "Range market"

            ]

        }





    # =========================
    # FINAL DECISION
    # =========================



    if score_buy >= 75:


        return {


            "signal":"BUY",

            "confidence":score_buy,

            "reason":reasons_buy

        }




    if score_sell >= 75:


        return {


            "signal":"SELL",

            "confidence":score_sell,

            "reason":reasons_sell

        }





    return {


        "signal":"NO_TRADE",

        "confidence":max(

            score_buy,

            score_sell

        ),

        "reason":[

            "Insufficient confirmation"

        ]

    }