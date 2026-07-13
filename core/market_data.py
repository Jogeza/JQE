"""
JQE Market Data Engine
Version: 0.1.1
"""


from datetime import datetime



class MarketData:


    def __init__(self):

        self.timeframe = "H1"



    def get_market_data(self, symbol):


        return {


            "symbol": symbol,

            "price": 0,

            "spread": 0,

            "timeframe": self.timeframe,

            "timestamp": datetime.now()


        }