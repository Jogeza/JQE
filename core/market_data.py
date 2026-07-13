"""
JQE Live Market Data Engine
Version: 0.1.3

Provides:
- Live tick data
- Historical candle data
- MT5 market feed
"""


import MetaTrader5 as mt5

from datetime import datetime

from core.mt5_connection import connect
from core.symbol_manager import SymbolManager




class MarketData:


    def __init__(self):

        self.timeframe = mt5.TIMEFRAME_H1

        self.connected = False

        self.symbol_manager = SymbolManager()



    def initialize(self):

        self.connected = connect()

        return self.connected




    def resolve_symbol(self, symbol):

        return self.symbol_manager.find_symbol(
            symbol
        )



    def get_market_data(self, symbol):


        if not self.connected:

            self.initialize()



        real_symbol = self.resolve_symbol(
            symbol
        )


        if real_symbol is None:

            return None



        tick = mt5.symbol_info_tick(
            real_symbol
        )


        if tick is None:

            return None



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

            "timestamp": datetime.now()


        }




    def get_candles(
            self,
            symbol,
            count=100):


        """
        Get OHLC candle data
        """


        if not self.connected:

            self.initialize()



        real_symbol = self.resolve_symbol(
            symbol
        )


        if real_symbol is None:

            return []



        rates = mt5.copy_rates_from_pos(

            real_symbol,

            self.timeframe,

            0,

            count

        )



        if rates is None:

            return []



        candles = []



        for candle in rates:


            candles.append({

                "time": datetime.fromtimestamp(
                    candle["time"]
                ),

                "open": candle["open"],

                "high": candle["high"],

                "low": candle["low"],

                "close": candle["close"],

                "volume": candle["tick_volume"]

            })



        return candles