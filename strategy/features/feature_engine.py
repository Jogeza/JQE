import math


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
        # VOLATILITY ANALYSIS
        #
        # Computed before momentum: a non-finite RSI fails closed below and
        # must not return before volatility is populated.

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

            volatility_score = 15

        #
        # MOMENTUM ANALYSIS
        #
        # Direction-relative to the detected trend: RSI strength aligned with
        # the trend is STRONG, opposed is WEAK. Without this the canonical
        # SELL gate (BEARISH + STRONG) is unreachable because the only legacy
        # bearish regime required RSI < 50 while absolute STRONG required
        # RSI > 60.

        rsi = float(latest["RSI_14"])

        if not math.isfinite(rsi):

            features["momentum"] = "UNKNOWN"

            features["confidence"] = 0

            return features

        trend = features["trend"]

        if (trend == "BULLISH" and rsi > 60) or (trend == "BEARISH" and rsi < 40):

            features["momentum"] = "STRONG"

            momentum_score = 30

        elif (trend == "BULLISH" and rsi < 40) or (trend == "BEARISH" and rsi > 60):

            features["momentum"] = "WEAK"

            momentum_score = 10

        else:

            features["momentum"] = "NEUTRAL"

            momentum_score = 20

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
