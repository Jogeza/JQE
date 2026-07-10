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
 ↓
Risk Controller
 ↓
Trade Decision
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

from risk.risk_controller import (
    evaluate_trade
)



def main():

    print("\n==========================")
    print("JQE ENGINE ONLINE")
    print("==========================")



    # =========================
    # CONNECT MT5
    # =========================

    if not connect():

        print(
            "❌ MT5 connection failed"
        )

        return



    # =========================
    # GET MARKET DATA
    # =========================

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



    # =========================
    # VALIDATE DATA
    # =========================

    if not validate_market_data(df):

        print(
            "❌ Data validation failed"
        )

        disconnect()

        return



    # =========================
    # INDICATORS
    # =========================

    df = calculate_indicators(df)



    # =========================
    # MARKET REGIME
    # =========================

    regime = detect_regime(df)



    # =========================
    # SIGNAL GENERATION
    # =========================

    signal = generate_signal(

        df,

        regime

    )



    # =========================
    # RISK CONTROL
    # =========================

    trade_plan = evaluate_trade(

        signal,

        df,

        balance=50,

        risk_percent=1

    )



    # =========================
    # DISPLAY RESULTS
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



    print(
        "\nRISK DECISION:"
    )

    print(
        trade_plan
    )



    disconnect()




if __name__ == "__main__":

    main()