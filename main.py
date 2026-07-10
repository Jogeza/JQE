from core.mt5_connection import (
    connect,
    disconnect
)

from core.market_data import (
    get_candles
)



def main():


    if not connect():

        return



    data = get_candles(

        symbol="XAUUSD",

        timeframe="M5",

        count=100

    )



    if data is not None:

        print(
            data.tail()
        )



    disconnect()



if __name__ == "__main__":

    main()