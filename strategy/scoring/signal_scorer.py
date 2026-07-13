class SignalScorer:


    def evaluate(
        self,
        intelligence,
        signal
    ):

        score = 0

        reasons = []


        #
        # TREND SCORE
        #

        if intelligence["trend"] in [
            "BULLISH",
            "BEARISH"
        ]:

            score += 30

            reasons.append(
                "Trend alignment"
            )


        #
        # MOMENTUM SCORE
        #

        if intelligence["momentum"] == "STRONG":

            score += 25

            reasons.append(
                "Strong momentum confirmation"
            )


        elif intelligence["momentum"] == "NEUTRAL":

            score += 10



        #
        # VOLATILITY SCORE
        #

        if intelligence["volatility"] == "NORMAL":

            score += 20

            reasons.append(
                "Controlled volatility"
            )


        #
        # MARKET REGIME SCORE
        #

        if intelligence["regime"] == "TRENDING":

            score += 25

            reasons.append(
                "Trending market condition"
            )


        elif intelligence["regime"] == "RANGING":

            score += 5



        #
        # QUALITY
        #

        if score >= 90:

            quality = "HIGH"


        elif score >= 70:

            quality = "GOOD"


        elif score >= 50:

            quality = "WEAK"


        else:

            quality = "POOR"



        return {

            "action": signal["action"],

            "score": score,

            "quality": quality,

            "confidence": score,

            "reasons": reasons

        }