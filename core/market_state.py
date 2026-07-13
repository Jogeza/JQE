"""
JQE Market State Intelligence
Version: 0.1.3

Combines:
- Trend
- Volatility
- Liquidity
"""




class MarketState:



    def analyze(self, market):


        if market is None:

            return None




        symbol = market["symbol"]





        #
        # Trend intelligence
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
        # Volatility intelligence
        #

        volatility_data = market.get(

            "volatility_analysis",

            {}

        )


        volatility = volatility_data.get(

            "volatility",

            "UNKNOWN"

        )





        #
        # Liquidity analysis
        #

        spread = market.get(

            "spread",

            999

        )



        if spread < 5:

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


            "price": market.get("price"),


            "atr": volatility_data.get("atr")


        }







    def calculate_score(

            self,

            trend,

            volatility,

            liquidity):



        score = 50





        #
        # Trend weight
        #

        if trend in [

            "BULLISH",

            "BEARISH"

        ]:

            score += 20





        #
        # Volatility weight
        #

        if volatility == "HIGH":

            score += 15


        elif volatility == "MEDIUM":

            score += 10






        #
        # Liquidity weight
        #

        if liquidity == "GOOD":

            score += 10





        return score