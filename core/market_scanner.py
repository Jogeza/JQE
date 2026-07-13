"""
JQE Autonomous Market Scanner
Version: 0.1.3

Integrated with:
- Live MT5 data
- Symbol Manager
- Trend Analysis Engine
"""


from core.market_data import MarketData
from core.market_state import MarketState

from analytics.trend_analysis import TrendAnalyzer




class MarketScanner:



    def __init__(self, symbols=None):


        self.symbols = symbols or [

            "GOLD",
            "BTCUSD",
            "DOW30",
            "EURUSD"

        ]


        self.data_engine = MarketData()

        self.state_engine = MarketState()

        self.trend_engine = TrendAnalyzer()




    def scan(self):

        """
        Backward compatibility
        """

        return self.autonomous_scan()




    def autonomous_scan(self):


        results = []



        for symbol in self.symbols:



            #
            # Get live market data
            #

            market_data = self.data_engine.get_market_data(
                symbol
            )



            if market_data is None:


                results.append({

                    "symbol": symbol,

                    "trend": "UNKNOWN",

                    "volatility": "UNKNOWN",

                    "liquidity": "UNKNOWN",

                    "market_score": 0,

                    "trade_ready": False

                })

                continue




            #
            # Get candle history
            #

            candles = self.data_engine.get_candles(

                symbol,

                100

            )




            #
            # Analyze trend
            #

            trend_result = self.trend_engine.analyze(

                candles

            )




            #
            # Pass intelligence
            #

            market_data["trend_analysis"] = trend_result




            market_state = self.state_engine.analyze(

                market_data

            )




            results.append(

                market_state

            )



        return results