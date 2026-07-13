class SignalEngine:


    def generate(
        self,
        intelligence
    ):

        signal = {

            "action": "HOLD",

            "reason": "",

            "confidence": 0

        }


        trend = intelligence["trend"]

        momentum = intelligence["momentum"]

        volatility = intelligence["volatility"]

        regime = intelligence["regime"]

        confidence = intelligence["confidence"]



        # TRENDING MARKET

        if regime == "TRENDING":


            if (
                trend == "BULLISH"
                and
                momentum == "STRONG"
            ):

                signal["action"] = "BUY"

                signal["reason"] = (
                    "Bullish trend + strong momentum"
                )



            elif (
                trend == "BEARISH"
                and
                momentum == "STRONG"
            ):

                signal["action"] = "SELL"

                signal["reason"] = (
                    "Bearish trend + strong momentum"
                )



        # HIGH VOLATILITY

        elif regime == "HIGH_VOLATILITY":


            signal["action"] = "HOLD"

            signal["reason"] = (
                "High volatility protection"
            )



        # RANGE MARKET

        elif regime in [
            "RANGING",
            "SIDEWAYS"
        ]:


            signal["action"] = "HOLD"

            signal["reason"] = (
                "No clear market direction"
            )



        signal["confidence"] = confidence


        return signal