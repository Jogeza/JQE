from core.mt5_connection import connect, disconnect

from core.market_data import get_candles

from core.data_validator import validate_market_data

from core.indicators import calculate_indicators



def main():


    if not connect():

        return



    df = get_candles(

        symbol="XAUUSD",

        timeframe="M5",

        count=500

    )



    if validate_market_data(df):


        df = calculate_indicators(df)


        print("\nLATEST MARKET ANALYSIS")

        print(
            df.tail()
        )



    disconnect()




if __name__ == "__main__":

    main()