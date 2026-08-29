from pathlib import Path

import MetaTrader5 as mt5

from core.logger import logger



def connect(*, terminal_path: Path | None = None, login: int | None = None,
            password: str | None = None, server: str | None = None):

    if terminal_path is not None:
        path = Path(terminal_path).expanduser().resolve()
        if not path.is_file():
            logger.error("MT5 terminal path does not exist: {}", path)
            return False
        initialized = mt5.initialize(str(path))
    else:
        initialized = mt5.initialize()

    if not initialized:

        logger.error(
            "MT5 connection failed"
        )

        return False


    if login is not None and not mt5.login(login, password=password, server=server):
        logger.error("MT5 account login failed for account {}", login)
        mt5.shutdown()
        return False

    logger.info("MT5 connection successful")


    return True



def disconnect():

    mt5.shutdown()

    logger.info(
        "MT5 disconnected"
    )
