import MetaTrader5 as mt5

from core.logger import logger



def connect():

    if not mt5.initialize():

        logger.error(
            "MT5 connection failed"
        )

        return False


    logger.info(
        "MT5 connection successful"
    )


    return True



def disconnect():

    mt5.shutdown()

    logger.info(
        "MT5 disconnected"
    )