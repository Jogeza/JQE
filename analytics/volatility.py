"""
JQE Volatility Engine
Version: 0.1.3

Calculates market volatility using ATR.
"""


class VolatilityAnalyzer:



    def calculate_atr(
        self,
        candles,
        period=14
    ):

        """
        Average True Range calculation
        """


        if len(candles) < period + 1:

            return None



        true_ranges = []



        for i in range(1, len(candles)):


            high = candles[i]["high"]

            low = candles[i]["low"]

            previous_close = candles[i-1]["close"]



            tr = max(

                high - low,

                abs(high - previous_close),

                abs(low - previous_close)

            )



            true_ranges.append(tr)



        atr = sum(

            true_ranges[-period:]

        ) / period



        return round(
            atr,
            5
        )





    def analyze(
        self,
        candles
    ):


        atr = self.calculate_atr(
            candles
        )



        if atr is None:


            return {


                "volatility": "UNKNOWN",

                "atr": None

            }




        #
        # Simple adaptive classification
        #

        if atr > 20:


            level = "HIGH"



        elif atr > 5:


            level = "MEDIUM"



        else:


            level = "LOW"




        return {


            "volatility": level,


            "atr": atr


        }