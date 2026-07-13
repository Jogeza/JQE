"""
JQE Institutional Backtest Runner
Version 0.1.0
"""


import MetaTrader5 as mt5
import pandas as pd


from core.market_data import get_market_data
from core.indicators import add_indicators
from core.regime import detect_regime

from strategy.signal_engine import generate_signal

from backtesting.engine import BacktestEngine

from analytics.performance import calculate_performance





SYMBOL = "XAUUSD"

TIMEFRAME = mt5.TIMEFRAME_M5

CANDLES = 5000




print()
print("==========================")
print("JQE v0.1.0 BACKTEST")
print("==========================")




if not mt5.initialize():

    print(
        "❌ MT5 Connection Failed"
    )

    quit()



print(
    "✅ MT5 Connected"
)



# ==========================
# LOAD DATA
# ==========================


df = get_market_data(

    SYMBOL,

    TIMEFRAME,

    CANDLES

)



if df is None:

    print(
        "No market data"
    )

    quit()



# indicators

df = add_indicators(df)



# ==========================
# ENGINE
# ==========================


engine = BacktestEngine(

    starting_balance=50

)




for i in range(200,len(df)):


    history = df.iloc[:i]


    candle = df.iloc[i]



    regime = detect_regime(

        history

    )



    signal = generate_signal(

        history,

        regime

    )



    engine.execute_trade(

        signal,

        candle

    )





# ==========================
# BASIC RESULTS
# ==========================


print()

print("==========================")

print(
    "JQE BACKTEST RESULTS"
)

print("==========================")


basic = engine.statistics()


for key,value in basic.items():

    print(

        key,

        ":",

        value

    )





# ==========================
# INSTITUTIONAL METRICS
# ==========================


print()

print("==========================")

print(
    "INSTITUTIONAL METRICS"
)

print("==========================")


metrics = calculate_performance(

    engine.trades,

    engine.equity_curve

)



for key,value in metrics.items():

    print(

        key,

        ":",

        value

    )



mt5.shutdown()