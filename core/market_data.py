"""
JQE Market Data Engine

Responsible for downloading
and validating market candles.
"""


import MetaTrader5 as mt5
import pandas as pd


from core.logger import logger

from core.symbol_manager import (
    validate_symbol
)



TIMEFRAME_MAP = {

    "M1": mt5.TIMEFRAME_M1,

    "M5": mt5.TIMEFRAME_M5,

    "M15": mt5.TIMEFRAME_M15,

    "H1": mt5.TIMEFRAME_H1,

    "H4": mt5.TIMEFRAME_H4,

    "D1": mt5.TIMEFRAME_D1

}



def get_candles(
        symbol: str,
        timeframe: str,
        count: int = 1000
):

    """
    Download historical candles.
    """


    if not validate_symbol(symbol):

        return None



    tf = TIMEFRAME_MAP.get(
        timeframe
    )


    if tf is None:

        raise ValueError(
            "Invalid timeframe"
        )



    rates = mt5.copy_rates_from_pos(

        symbol,

        tf,

        0,

        count

    )



    if rates is None:

        logger.error(
            "Failed downloading candles"
        )

        return None



    df = pd.DataFrame(
        rates
    )



    df["time"] = pd.to_datetime(

        df["time"],

        unit="s"

    )



    logger.info(

        f"Downloaded {len(df)} candles for {symbol}"

    )



    return df