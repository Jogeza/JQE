"""
JQE Market Score Engine
Version: 0.1.3

Calculates institutional market confidence score.

Weights:

Trend       40%
Volatility  25%
Liquidity   20%
Momentum    15%
"""


class MarketScore:



    def calculate(
        self,
        trend,
        volatility,
        liquidity,
        momentum="NEUTRAL"
    ):


        score = 0



        #
        # Trend Score (40)
        #

        if trend in [

            "BULLISH",

            "BEARISH"

        ]:

            score += 40




        #
        # Volatility Score (25)
        #

        if volatility == "HIGH":

            score += 25


        elif volatility == "MEDIUM":

            score += 15


        elif volatility == "LOW":

            score += 10





        #
        # Liquidity Score (20)
        #

        if liquidity == "GOOD":

            score += 20


        elif liquidity == "MEDIUM":

            score += 10





        #
        # Momentum Score (15)
        #

        if momentum == "STRONG":

            score += 15


        elif momentum == "MODERATE":

            score += 10





        return score