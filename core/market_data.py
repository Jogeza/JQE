"""
JQE Live Market Data Engine
Version: 0.1.2

Responsible for:
- Connecting to MT5
- Resolving broker symbols
- Reading live market prices
- Returning market information
"""


import MetaTrader5 as mt5

from datetime import datetime

from core.mt5_connection import connect
from core.symbol_manager import SymbolManager




class MarketData:



    def __init__(self):

        self.timeframe = "H1"

        self.connected = False

        self.symbol_manager = SymbolManager()



    def initialize(self):

        """
        Initialize MT5 connection
        """

        self.connected = connect()

        return self.connected




    def get_market_data(self, symbol):


        """
        Get live market data
        """



        if not self.connected:

            self.initialize()



        #
        # Find real broker symbol
        #
        real_symbol = self.symbol_manager.find_symbol(
            symbol
        )



        if real_symbol is None:


            return {


                "symbol": symbol,

                "price": 0,

                "bid": 0,

                "ask": 0,

                "spread": 0,

                "timeframe": self.timeframe,

                "timestamp": datetime.now()


            }




        #
        # Request live tick data
        #
        tick = mt5.symbol_info_tick(
            real_symbol
        )



        if tick is None:


            return {


                "symbol": symbol,

                "price": 0,

                "bid": 0,

                "ask": 0,

                "spread": 0,

                "timeframe": self.timeframe,

                "timestamp": datetime.now()


            }




        #
        # Calculate spread
        #
        spread = round(

            tick.ask - tick.bid,

            5

        )




        return {

    "symbol": symbol,

    "broker_symbol": real_symbol,

    "price": tick.last,

    "bid": tick.bid,

    "ask": tick.ask,

    "spread": spread,

    "timeframe": self.timeframe,

    "timestamp": datetime.now()

}


        