class DynamicRisk:


    def calculate(
        self,
        intelligence,
        balance
    ):


        confidence = (
            intelligence["confidence"]
        )


        regime = (
            intelligence["regime"]
        )


        risk_percent = 1.0



        #
        # Confidence adjustment
        #

        if confidence >= 90:

            risk_percent = 2.0


        elif confidence >= 70:

            risk_percent = 1.5


        elif confidence >= 50:

            risk_percent = 1.0


        else:

            risk_percent = 0.5



        #
        # Market condition adjustment
        #

        if regime == "HIGH_VOLATILITY":

            risk_percent *= 0.5



        elif regime == "RANGING":

            risk_percent *= 0.75



        risk_amount = (
            balance *
            risk_percent /
            100
        )


        return {


            "risk_percent":
                round(
                    risk_percent,
                    2
                ),


            "risk_amount":
                round(
                    risk_amount,
                    2
                )

        }