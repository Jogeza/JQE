"""
JQE Feature Engine
Version: 0.2.0

Generates trading intelligence.
"""


from strategy.features.market_regime import MarketRegime





class FeatureEngine:



    def __init__(self):

        self.regime_engine = MarketRegime()





    def analyze(
        self,
        df
    ):


        latest = df.iloc[-1]


        features = {}





        #
        # TREND
        #

        ema50 = latest["EMA_50"]

        ema200 = latest["EMA_200"]



        if ema50 > ema200:


            features["trend"] = "BULLISH"



        else:


            features["trend"] = "BEARISH"






        #
        # MOMENTUM
        #

        rsi = latest["RSI_14"]



        if rsi > 60:


            features["momentum"] = "STRONG"



        elif rsi < 40:


            features["momentum"] = "WEAK"



        else:


            features["momentum"] = "NEUTRAL"







        #
        # VOLATILITY
        #

        atr = latest["ATR_14"]


        average_atr = df["ATR_14"].mean()



        if atr > average_atr:


            features["volatility"] = "HIGH"



        else:


            features["volatility"] = "NORMAL"







        #
        # REGIME
        #

        features["regime"] = self.regime_engine.analyze(

            features

        )






        #
        # CONFIDENCE
        #

        confidence = 0



        if features["trend"] != "UNKNOWN":

            confidence += 30



        if features["momentum"] == "STRONG":

            confidence += 30


        elif features["momentum"] == "NEUTRAL":

            confidence += 20



        if features["volatility"] == "NORMAL":

            confidence += 20


        else:

            confidence += 10





        features["confidence"] = confidence




        return features