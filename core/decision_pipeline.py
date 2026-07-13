class DecisionPipeline:



    def decide(
        self,
        signal,
        score,
        risk
    ):


        if signal["action"] == "HOLD":

            return {

                "decision": "IGNORE",

                "reason": "No trading signal"

            }



        if score["quality"] == "POOR":

            return {

                "decision": "IGNORE",

                "reason": "Low quality trade"

            }



        if risk["risk_percent"] <= 0:

            return {

                "decision": "IGNORE",

                "reason": "Risk rejected"

            }



        return {

            "decision": signal["action"],

            "confidence": score["confidence"]

        }