"""
JQE Main Engine

Institutional Trading Architecture

Pipeline:

Market Data
    |
Validation
    |
Indicators
    |
Market Regime
    |
Signal Intelligence
    |
Risk Controller
    |
Execution Simulator
"""


from core.mt5_connection import connect, disconnect

from core.market_data import get_candles

from core.data_validator import validate_market_data

from core.indicators import calculate_indicators

from core.regime import detect_regime

from strategy.signal_engine import generate_signal

from risk.risk_controller import evaluate_trade

from execution.simulator import ExecutionSimulator




def main():


    print("\n==========================")
    print("JQE ENGINE ONLINE")
    print("==========================")



    # ==========================
    # MT5 CONNECTION
    # ==========================

    if not connect():

        print(
            "❌ MT5 connection failed"
        )

        return



    # ==========================
    # MARKET DATA
    # ==========================


    df = get_candles(

        symbol="XAUUSD",

        timeframe="M5",

        count=500

    )



    if df is None:

        print(
            "❌ Market data unavailable"
        )

        disconnect()

        return



    # ==========================
    # DATA VALIDATION
    # ==========================


    if not validate_market_data(df):

        print(
            "❌ Invalid market data"
        )

        disconnect()

        return



    # ==========================
    # INDICATORS
    # ==========================


    df = calculate_indicators(df)



    # ==========================
    # MARKET REGIME
    # ==========================


    regime = detect_regime(df)



    # ==========================
    # SIGNAL ENGINE
    # ==========================


    signal = generate_signal(

        df,

        regime

    )



    # ==========================
    # RISK ENGINE
    # ==========================


    trade_plan = evaluate_trade(

        signal,

        df,

        balance=50,

        risk_percent=1

    )



    # ==========================
    # EXECUTION ENGINE
    # ==========================


    executor = ExecutionSimulator(

        balance=50

    )



    order = None



    if trade_plan["approved"]:


        order = executor.create_order(

            symbol="XAUUSD",

            direction=trade_plan["signal"],

            entry=trade_plan["entry"],

            lot=trade_plan["lot"],

            stop_loss=trade_plan["stop_loss"],

            take_profit=trade_plan["take_profit"]

        )



    # ==========================
    # OUTPUT
    # ==========================


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



    print(
        "\nEXECUTION RESULT:"
    )

    print(
        order
    )



    print(
        "\nACCOUNT STATUS:"
    )

    print(
        executor.account_status()
    )



    disconnect()




if __name__ == "__main__":

    main()