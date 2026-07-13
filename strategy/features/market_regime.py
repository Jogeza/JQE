"""
JQE Market Regime Detector
Version: 0.2.0

Detects:
- Trending markets
- Ranging markets
- High volatility conditions

Backward compatible:
detect()
analyze()
"""


class MarketRegime:



    def detect(
        self,
        features=None,
        trend=None,
        volatility=None
    ):


        #
        # Support dictionary input
        #

        if features is not None:


            trend = features.get(

                "trend",

                "UNKNOWN"

            )


            volatility = features.get(

                "volatility",

                "UNKNOWN"

            )




        #
        # High volatility protection
        #

        if volatility == "HIGH":


            return "HIGH_VOLATILITY"




        #
        # Trend condition
        #

        if trend in [

            "BULLISH",

            "BEARISH"

        ]:


            return "TRENDING"





        return "RANGING"






    def analyze(
        self,
        features
    ):


        return self.detect(

            features=features

        )