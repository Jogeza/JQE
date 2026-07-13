"""
JQE Market State Intelligence
Version: 0.1.3
"""


class MarketState:



    def analyze(self, market):


        if market is None:

            return None



        symbol = market["symbol"]



        #
        # Get trend from analytics
        #

        trend_data = market.get(
            "trend_analysis",
            {}
        )



        trend = trend_data.get(

            "trend",

            "UNKNOWN"

        )



        #
        # Temporary volatility
        #

        volatility = "MEDIUM"



        #
        # Liquidity from spread
        #

        if market.get("spread", 999) < 5:

            liquidity = "GOOD"

        else:

            liquidity = "LOW"




        score = self.calculate_score(

            trend,

            volatility,

            liquidity

        )



        return {


            "symbol": symbol,


            "trend": trend,


            "volatility": volatility,


            "liquidity": liquidity,


            "market_score": score,


            "trade_ready": score >= 70,


            "price": market.get("price")


        }





    def calculate_score(

        self,

        trend,

        volatility,

        liquidity

    ):


        score = 50



        if trend in [

            "BULLISH",

            "BEARISH"

        ]:

            score += 20



        if volatility == "HIGH":

            score += 15


        elif volatility == "MEDIUM":

            score += 5



        if liquidity == "GOOD":

            score += 10



        return score