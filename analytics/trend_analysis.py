"""
JQE Trend Analysis Engine
Version: 0.1.3

Calculates market direction using:
- EMA 20
- EMA 50
"""


class TrendAnalyzer:



    def calculate_ema(
        self,
        prices,
        period
    ):

        """
        Calculate Exponential Moving Average
        """


        if len(prices) < period:

            return None



        multiplier = 2 / (period + 1)


        ema = prices[0]



        for price in prices[1:]:

            ema = (

                (price - ema)
                * multiplier

            ) + ema



        return round(
            ema,
            5
        )





    def analyze(
        self,
        candles
    ):


        """
        Determine market trend
        """


        if len(candles) < 50:

            return {

                "trend": "UNKNOWN",

                "ema20": None,

                "ema50": None

            }



        closes = [

            candle["close"]

            for candle in candles

        ]



        ema20 = self.calculate_ema(

            closes,

            20

        )


        ema50 = self.calculate_ema(

            closes,

            50

        )



        current_price = closes[-1]



        if ema20 > ema50 and current_price > ema20:


            trend = "BULLISH"



        elif ema20 < ema50 and current_price < ema20:


            trend = "BEARISH"



        else:


            trend = "SIDEWAYS"




        return {


            "trend": trend,

            "ema20": ema20,

            "ema50": ema50,

            "price": current_price

        }