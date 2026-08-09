import os
import pandas as pd


class HistoricalData:

    def __init__(
        self,
        base_folder="data/storage/symbols"
    ):

        self.base_folder = base_folder


        os.makedirs(
            self.base_folder,
            exist_ok=True
        )


    def save(
        self,
        df,
        symbol,
        timeframe
    ):

        symbol_folder = os.path.join(
            self.base_folder,
            symbol
        )


        os.makedirs(
            symbol_folder,
            exist_ok=True
        )


        file_path = os.path.join(
            symbol_folder,
            f"{timeframe}.csv"
        )


        df.to_csv(
            file_path,
            index=False
        )


        print(
            f"Saved {symbol} {timeframe}: {len(df)} candles"
        )


    def load(
        self,
        symbol,
        timeframe
    ):

        file_path = os.path.join(
            self.base_folder,
            symbol,
            f"{timeframe}.csv"
        )


        if not os.path.exists(file_path):

            raise FileNotFoundError(
                f"No data found for {symbol} {timeframe}"
            )


        return pd.read_csv(
            file_path,
            parse_dates=["time"]
        )