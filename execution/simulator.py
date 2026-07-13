"""
JQE Institutional Execution Simulator
Version 0.1.1

Forward-only trade simulation.
No look-ahead bias.
"""


def simulate_trade(

        signal,

        current_index,

        dataframe

):


    direction = signal.get(
        "signal"
    )


    if direction not in [

        "BUY",

        "SELL"

    ]:

        return None



    entry = dataframe.iloc[current_index]["close"]


    atr = dataframe.iloc[current_index]["ATR"]



    if atr <= 0:

        return None



    stop_distance = atr * 1.5

    target_distance = atr * 3




    if direction == "BUY":


        stop = entry - stop_distance

        target = entry + target_distance



    else:


        stop = entry + stop_distance

        target = entry - target_distance





    # ONLY future candles

    future = dataframe.iloc[

        current_index + 1 :

        current_index + 20

    ]



    for _, candle in future.iterrows():



        if direction == "BUY":



            if candle["low"] <= stop:


                return {


                    "profit": -1,

                    "result":"LOSS"

                }



            if candle["high"] >= target:


                return {


                    "profit": 3,

                    "result":"WIN"

                }







        if direction == "SELL":



            if candle["high"] >= stop:


                return {


                    "profit": -1,

                    "result":"LOSS"

                }



            if candle["low"] <= target:


                return {


                    "profit":3,

                    "result":"WIN"

                }





    return {


        "profit":0,

        "result":"TIMEOUT"

    }