"""
JQE Main Engine

Pipeline:

MT5
 ↓
Market Data
 ↓
Data Validation
 ↓
Indicators
 ↓
Market Regime Detection
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



def main():


    # Connect MT5

    if not connect():

        print(
            "❌ MT5 connection failed"
        )

        return



    # Get market data

    df = get_candles(

        symbol="XAUUSD",

        timeframe="M5",

        count=500

    )



    if df is None:

        print(
            "❌ No market data"
        )

        disconnect()

        return



    # Validate data

    if not validate_market_data(df):

        print(
            "❌ Invalid market data"
        )

        disconnect()

        return



    # Calculate indicators

    df = calculate_indicators(df)



    # Detect market condition

    regime = detect_regime(df)



    print("\n==========================")

    print("JQE MARKET ANALYSIS")

    print("==========================")



    print(
        df.tail()
    )



    print(
        "\nMARKET REGIME:",
        regime
    )



    disconnect()




if __name__ == "__main__":

    main()