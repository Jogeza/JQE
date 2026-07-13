"""
JQE Signal Engine
Version: 0.2.0

Converts market intelligence
into trading decisions.
"""


class SignalEngine:



    def generate(
        self,
        intelligence
    ):


        signal = {


            "action": "WAIT",


            "reason": "",


            "confidence": 0,


            "quality": "LOW"

        }





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


        confidence = intelligence.get(

            "confidence",

            0

        )





        #
        # HIGH VOLATILITY PROTECTION
        #

        if regime == "HIGH_VOLATILITY":


            signal["action"] = "WAIT"


            signal["reason"] = (

                "High volatility protection"

            )



            signal["confidence"] = confidence


            return signal





        #
        # TRENDING MARKET
        #

        if regime == "TRENDING":



            if (

                trend == "BULLISH"

                and

                momentum == "STRONG"

            ):


                signal["action"] = "BUY"


                signal["reason"] = (

                    "Bullish trend confirmed "
                    "by strong momentum"

                )



            elif (

                trend == "BEARISH"

                and

                momentum == "STRONG"

            ):


                signal["action"] = "SELL"


                signal["reason"] = (

                    "Bearish trend confirmed "
                    "by strong momentum"

                )



            else:


                signal["action"] = "WAIT"


                signal["reason"] = (

                    "Trend confirmation missing"

                )





        #
        # RANGE MARKET
        #

        elif regime in [

            "RANGING",

            "SIDEWAYS"

        ]:


            signal["action"] = "WAIT"


            signal["reason"] = (

                "No directional advantage"

            )





        else:


            signal["action"] = "WAIT"


            signal["reason"] = (

                "Unknown market condition"

            )





        #
        # Confidence classification
        #

        signal["confidence"] = confidence



        if confidence >= 85:


            signal["quality"] = "HIGH"



        elif confidence >= 70:


            signal["quality"] = "MEDIUM"



        else:


            signal["quality"] = "LOW"





        return signal