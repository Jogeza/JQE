"""
JQE Signal Scorer
Version: 0.2.0

Calculates trade confidence.
"""


class SignalScorer:



    def evaluate(
        self,
        intelligence,
        signal
    ):


        score = 0

        reasons = []



        trend = intelligence.get(
            "trend",
            "UNKNOWN"
        )


        momentum = intelligence.get(
            "momentum",
            "UNKNOWN"
        )


        volatility = intelligence.get(
            "volatility",
            "UNKNOWN"
        )


        regime = intelligence.get(
            "regime",
            "UNKNOWN"
        )





        #
        # TREND SCORE
        #

        if trend in [

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

        if momentum == "STRONG":


            score += 25


            reasons.append(

                "Strong momentum confirmation"

            )


        elif momentum == "MODERATE":


            score += 15


            reasons.append(

                "Moderate momentum"

            )





        #
        # VOLATILITY SCORE
        #

        if volatility in [

            "LOW",
            "MEDIUM"

        ]:


            score += 20


            reasons.append(

                "Controlled volatility"

            )


        elif volatility == "HIGH":


            score += 5


            reasons.append(

                "High volatility risk"

            )






        #
        # MARKET REGIME SCORE
        #

        if regime == "TRENDING":


            score += 25


            reasons.append(

                "Trending market condition"

            )


        elif regime == "RANGING":


            score += 5


            reasons.append(

                "Range market"

            )





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


            "action": signal.get(

                "action",

                "WAIT"

            ),


            "score": score,


            "quality": quality,


            "confidence": score,


            "reasons": reasons

        }