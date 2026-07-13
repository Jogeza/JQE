"""
JQE Decision Pipeline
Version: 0.2.0

Supports:

1. Candle DataFrame analysis
2. Market Scanner intelligence

"""



from strategy.features.feature_engine import FeatureEngine

from strategy.signal_engine import SignalEngine

from strategy.scoring.signal_scorer import SignalScorer





class DecisionPipeline:



    def __init__(self):


        self.feature_engine = FeatureEngine()


        self.signal_engine = SignalEngine()


        self.signal_scorer = SignalScorer()





    def analyze(
        self,
        data,
        symbol="UNKNOWN"
    ):



        #
        # DATAFRAME MODE
        #

        if hasattr(data, "iloc"):


            intelligence = self.feature_engine.analyze(

                data

            )



        #
        # SCANNER INTELLIGENCE MODE
        #

        elif isinstance(data, dict):


            intelligence = {


                "trend": data.get(

                    "trend",

                    "UNKNOWN"

                ),


                "momentum": data.get(

                    "momentum",

                    "UNKNOWN"

                ),


                "volatility": data.get(

                    "volatility",

                    "UNKNOWN"

                ),


                "regime": data.get(

                    "regime",

                    "TRENDING"

                ),


                "confidence": data.get(

                    "market_score",

                    0

                )

            }



        else:


            intelligence = {


                "trend":"UNKNOWN",

                "momentum":"UNKNOWN",

                "volatility":"UNKNOWN",

                "regime":"UNKNOWN",

                "confidence":0

            }





        signal = self.signal_engine.generate(

            intelligence

        )





        decision = self.signal_scorer.evaluate(

            intelligence,

            signal

        )





        return {


            "symbol": symbol,


            "intelligence": intelligence,


            "signal": signal,


            "decision": decision

        }





    def decide(
        self,
        *args
    ):



        symbol = "UNKNOWN"

        data = None





        for item in args:


            if isinstance(item, str):


                symbol = item



            else:


                data = item





        if data is None:


            return {


                "action":"WAIT",

                "confidence":0,

                "score":0,

                "quality":"POOR"

            }





        result = self.analyze(

            data,

            symbol

        )





        return result["decision"]