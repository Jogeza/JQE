import MetaTrader5 as mt5
import pandas as pd


class MarketLoader:

    def __init__(self, symbol="XAUUSD"):
        self.symbol = symbol


    def connect(self):

        if not mt5.initialize():
            raise Exception("MT5 initialization failed")

        print("MT5 connected")


    def get_candles(
        self,
        timeframe=mt5.TIMEFRAME_M15,
        count=1000
    ):

        rates = mt5.copy_rates_from_pos(
            self.symbol,
            timeframe,
            0,
            count
        )


        if rates is None:
            raise Exception(
                f"No data received for {self.symbol}"
            )


        df = pd.DataFrame(rates)


        df["time"] = pd.to_datetime(
            df["time"],
            unit="s"
        )


        return df