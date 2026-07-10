"""
JQE Main Engine

Pipeline:

MT5
 ↓
Market Data Engine
 ↓
Data Validation
 ↓
Indicator Engine
 ↓
Market Regime Detection
 ↓
Signal Intelligence
"""


from core.mt5_connection import (
    connect,
    disconnect
)

from core.market_data import (
    get_candles
)

from core.data_validator import (
    validate_market_data
)

from core.indicators import (
    calculate_indicators
)

from core.regime import (
    detect_regime
)

from strategy.signal_engine import (
    generate_signal
)



def main():


    print("\n==========================")
    print("JQE ENGINE ONLINE")
    print("==========================")



    # =========================
    # CONNECT TO MT5
    # =========================

    if not connect():

        print(
            "❌ MT5 connection failed"
        )

        return



    # =========================
    # LOAD MARKET DATA
    # =========================

    df = get_candles(

        symbol="XAUUSD",

        timeframe="M5",

        count=500

    )



    if df is None:


        print(
            "❌ No market data received"
        )

        disconnect()

        return



    # =========================
    # VALIDATE DATA
    # =========================

    if not validate_market_data(df):


        print(
            "❌ Market data validation failed"
        )

        disconnect()

        return



    # =========================
    # ADD INDICATORS
    # =========================

    df = calculate_indicators(df)



    # =========================
    # DETECT MARKET CONDITION
    # =========================

    regime = detect_regime(df)



    # =========================
    # GENERATE SIGNAL
    # =========================

    signal = generate_signal(

        df,

        regime

    )



    # =========================
    # DISPLAY ANALYSIS
    # =========================


    print("\n==========================")
    print("JQE MARKET ANALYSIS")
    print("==========================")



    print(
        df.tail()
    )



    print(
        "\nMARKET REGIME:"
    )

    print(
        regime
    )



    print(
        "\nTRADE SIGNAL:"
    )

    print(
        signal
    )



    disconnect()




if __name__ == "__main__":

    main()