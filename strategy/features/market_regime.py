class MarketRegime:


    def detect(
        self,
        features
    ):


        trend = features["trend"]

        momentum = features["momentum"]

        volatility = features["volatility"]



        if (
            trend in [
                "BULLISH",
                "BEARISH"
            ]
            and
            momentum == "STRONG"
        ):

            return "TRENDING"



        if volatility == "HIGH":

            return "HIGH_VOLATILITY"



        if (
            momentum == "NEUTRAL"
        ):

            return "SIDEWAYS"



        return "RANGING"