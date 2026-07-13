import pandas as pd


class Indicators:


    @staticmethod
    def ema(df, period):

        df[f"EMA_{period}"] = (
            df["close"]
            .ewm(
                span=period,
                adjust=False
            )
            .mean()
        )

        return df



    @staticmethod
    def rsi(
        df,
        period=14
    ):

        delta = df["close"].diff()


        gain = delta.where(
            delta > 0,
            0
        )


        loss = -delta.where(
            delta < 0,
            0
        )


        avg_gain = (
            gain
            .rolling(period)
            .mean()
        )


        avg_loss = (
            loss
            .rolling(period)
            .mean()
        )


        rs = avg_gain / avg_loss


        df[f"RSI_{period}"] = (
            100 -
            (100 / (1 + rs))
        )


        return df



    @staticmethod
    def atr(
        df,
        period=14
    ):

        high_low = (
            df["high"]
            -
            df["low"]
        )


        high_close = abs(
            df["high"]
            -
            df["close"].shift()
        )


        low_close = abs(
            df["low"]
            -
            df["close"].shift()
        )


        true_range = pd.concat(
            [
                high_low,
                high_close,
                low_close
            ],
            axis=1
        ).max(axis=1)


        df[f"ATR_{period}"] = (
            true_range
            .rolling(period)
            .mean()
        )


        return df



    @classmethod
    def add_all(cls, df):

        df = cls.ema(df, 50)

        df = cls.ema(df, 200)

        df = cls.rsi(df)

        df = cls.atr(df)

        return df