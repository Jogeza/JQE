"""
JQE Autonomous Market Scanner
Version: 0.1.1

Responsible for:
- Scanning market universe
- Collecting market data
- Evaluating market conditions
- Ranking opportunities
"""


from core.market_data import MarketData
from core.market_state import MarketState



class MarketScanner:


    def __init__(self, symbols=None):

        # Backward compatible with JQE v0.1.0
        # Allows:
        # MarketScanner(symbols)

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
        Legacy method
        Used by JQE core engine
        """

        return self.autonomous_scan()



    def autonomous_scan(self):

        """
        Autonomous market analysis
        """

        results = []


        for symbol in self.symbols:


            market_data = self.data_engine.get_market_data(
                symbol
            )


            market_state = self.state_engine.analyze(
                market_data
            )


            results.append(
                market_state
            )


        return results