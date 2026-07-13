"""
JQE Autonomous Market Scanner
Version: 0.1.3

Responsibilities:
- Scan market universe
- Collect market data
- Pass data to intelligence engine
- Handle missing market data safely
"""


from core.market_data import MarketData
from core.market_state import MarketState




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




    def scan(self):

        """
        Legacy compatibility
        Used by JQE engine
        """

        return self.autonomous_scan()




    def autonomous_scan(self):

        """
        Autonomous market scanning
        """

        results = []



        for symbol in self.symbols:



            market_data = self.data_engine.get_market_data(
                symbol
            )



            #
            # Safety handling
            #
            # If MT5 has no data,
            # keep the market in the report
            #

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




            market_state = self.state_engine.analyze(
                market_data
            )



            if market_state is not None:

                results.append(
                    market_state
                )



        return results