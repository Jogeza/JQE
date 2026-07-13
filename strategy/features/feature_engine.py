class FeatureEngine:


    def analyze(self, df):

        latest = df.iloc[-1]


        features = {}


        #
        # TREND ANALYSIS
        #

        ema50 = latest["EMA_50"]
        ema200 = latest["EMA_200"]


        if ema50 > ema200:

            features["trend"] = "BULLISH"

            trend_score = 30


        else:

            features["trend"] = "BEARISH"

            trend_score = 30



        #
        # MOMENTUM ANALYSIS
        #

        rsi = latest["RSI_14"]


        if rsi > 60:

            features["momentum"] = "STRONG"

            momentum_score = 30


        elif rsi < 40:

            features["momentum"] = "WEAK"

            momentum_score = 10


        else:

            features["momentum"] = "NEUTRAL"

            momentum_score = 20



        #
        # VOLATILITY ANALYSIS
        #

        atr = latest["ATR_14"]


        average_atr = (
            df["ATR_14"]
            .mean()
        )


        if atr > average_atr:

            features["volatility"] = "HIGH"

            volatility_score = 20


        else:

            features["volatility"] = "NORMAL"

            volatility_score = 10



        #
        # MARKET CONFIDENCE
        #

        confidence = (
            trend_score
            +
            momentum_score
            +
            volatility_score
        )


        features["confidence"] = confidence


        return features