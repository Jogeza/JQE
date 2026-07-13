"""
JQE Market State Intelligence
Version: 0.1.3
"""


from analytics.market_score import MarketScore





class MarketState:



    def __init__(self):


        self.score_engine = MarketScore()






    def analyze(
        self,
        market
    ):


        if market is None:

            return None





        symbol = market["symbol"]





        trend_data = market.get(

            "trend_analysis",

            {}

        )


        trend = trend_data.get(

            "trend",

            "UNKNOWN"

        )





        volatility_data = market.get(

            "volatility_analysis",

            {}

        )


        volatility = volatility_data.get(

            "volatility",

            "UNKNOWN"

        )





        momentum_data = market.get(

            "momentum_analysis",

            {}

        )


        momentum = momentum_data.get(

            "momentum",

            "UNKNOWN"

        )





        spread = market.get(

            "spread",

            999

        )



        if spread < 5:

            liquidity = "GOOD"


        else:

            liquidity = "LOW"






        score = self.score_engine.calculate(

            trend,

            volatility,

            liquidity,

            momentum

        )






        return {


            "symbol": symbol,


            "trend": trend,


            "volatility": volatility,


            "momentum": momentum,


            "liquidity": liquidity,


            "market_score": score,


            "trade_ready": score >= 70,


            "price": market.get("price"),


            "atr": volatility_data.get("atr"),


            "rsi": momentum_data.get("rsi")

        }