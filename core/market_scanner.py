"""
JQE Autonomous Market Scanner
Version: 0.1.3
"""


from core.market_data import MarketData
from core.market_state import MarketState


from analytics.trend_analysis import TrendAnalyzer
from analytics.volatility import VolatilityAnalyzer
from analytics.momentum import MomentumAnalyzer





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

        self.volatility_engine = VolatilityAnalyzer()

        self.momentum_engine = MomentumAnalyzer()






    def scan(self):

        return self.autonomous_scan()






    def autonomous_scan(self):


        results = []



        for symbol in self.symbols:



            market_data = self.data_engine.get_market_data(

                symbol

            )



            if market_data is None:


                results.append({


                    "symbol": symbol,


                    "trend": "UNKNOWN",


                    "volatility": "UNKNOWN",


                    "momentum": "UNKNOWN",


                    "liquidity": "UNKNOWN",


                    "market_score": 0,


                    "trade_ready": False


                })


                continue





            candles = self.data_engine.get_candles(

                symbol,

                100

            )





            trend_result = self.trend_engine.analyze(

                candles

            )




            volatility_result = self.volatility_engine.analyze(

                candles

            )




            momentum_result = self.momentum_engine.analyze(

                candles

            )





            market_data["trend_analysis"] = trend_result


            market_data["volatility_analysis"] = volatility_result


            market_data["momentum_analysis"] = momentum_result





            market_state = self.state_engine.analyze(

                market_data

            )



            results.append(

                market_state

            )



        return results