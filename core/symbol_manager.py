"""
JQE Symbol Manager

Handles MT5 market symbols.
"""

import MetaTrader5 as mt5

from core.logger import logger



def validate_symbol(symbol: str) -> bool:
    """
    Check if symbol exists in MT5.
    """

    info = mt5.symbol_info(symbol)


    if info is None:

        logger.error(
            f"Symbol not found: {symbol}"
        )

        return False


    if not info.visible:

        mt5.symbol_select(
            symbol,
            True
        )


    logger.info(
        f"Symbol validated: {symbol}"
    )


    return True



def get_symbol_info(symbol: str):

    """
    Returns MT5 symbol information.
    """

    info = mt5.symbol_info(symbol)


    if info is None:

        return None


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