"""
JQE Symbol Manager
Version: 0.1.2

Handles:
- MT5 symbol validation
- Broker symbol mapping
- Automatic discovery
"""


import MetaTrader5 as mt5

from core.logger import logger



class SymbolManager:



    def __init__(self):


        self.symbol_aliases = {


            "GOLD": [

                "GOLD",
                "XAUUSD",
                "XAUUSDm",
                "XAUUSD.pro",
                "GOLD#"

            ],



            "BTCUSD": [

                "BTCUSD",
                "BTCUSDm",
                "BTCUSD.pro"

            ],



            "DOW30": [

                "DOW30",
                "US30",
                "DJ30",
                "WS30"

            ],



            "EURUSD": [

                "EURUSD",
                "EURUSDm",
                "EURUSD.pro"

            ]


        }



    def find_symbol(self, requested_symbol):


        """
        Find real broker symbol.
        """


        candidates = self.symbol_aliases.get(
            requested_symbol,
            [requested_symbol]
        )



        for symbol in candidates:


            info = mt5.symbol_info(symbol)



            if info is not None:


                if not info.visible:

                    mt5.symbol_select(
                        symbol,
                        True
                    )


                logger.info(
                    f"Symbol mapped: {requested_symbol} -> {symbol}"
                )


                return symbol



        logger.error(
            f"No broker symbol found for {requested_symbol}"
        )


        return None





    def validate_symbol(self, symbol):


        result = self.find_symbol(symbol)


        return result is not None





    def get_symbol_info(self, symbol):


        real_symbol = self.find_symbol(
            symbol
        )


        if real_symbol is None:

            return None



        info = mt5.symbol_info(
            real_symbol
        )



        return {


            "name": info.name,


            "digits": info.digits,


            "spread": info.spread,


            "volume_min": info.volume_min,


            "volume_max": info.volume_max,


            "tick_size": info.trade_tick_size,


            "tick_value": info.trade_tick_value,


            "contract_size": info.trade_contract_size

        }