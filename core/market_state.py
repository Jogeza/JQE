"""
JQE Market State Intelligence
Version: 0.1.1
"""


class MarketState:



    def analyze(self, market):


        symbol = market["symbol"]



        if symbol == "GOLD":

            trend = "BULLISH"
            volatility = "HIGH"
            liquidity = "GOOD"



        elif symbol == "BTCUSD":

            trend = "SIDEWAYS"
            volatility = "MEDIUM"
            liquidity = "GOOD"



        elif symbol == "DOW30":

            trend = "BULLISH"
            volatility = "MEDIUM"
            liquidity = "GOOD"



        elif symbol == "EURUSD":

            trend = "BEARISH"
            volatility = "LOW"
            liquidity = "GOOD"



        else:

            trend = "UNKNOWN"
            volatility = "LOW"
            liquidity = "UNKNOWN"



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

            "trade_ready": score >= 70

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