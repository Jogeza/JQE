from pathlib import Path

import MetaTrader5 as mt5

from core.logger import logger
from core.mt5_session import mt5_session

_LEGACY_SESSION_OWNER = object()


def connect(*, terminal_path: Path | None = None, login: int | None = None,
            password: str | None = None, server: str | None = None,
            _session_owner: object = _LEGACY_SESSION_OWNER):
    with mt5_session.lock:
        if not mt5_session.reserve(_session_owner):
            logger.error("MT5 process-global session already owned")
            return False
        try:
            result = _initialize(terminal_path=terminal_path, login=login, password=password, server=server)
            if result is True:
                mt5_session.activate(_session_owner)
            else:
                mt5_session.invalidate()
            return result is True
        except BaseException:
            mt5_session.invalidate()
            raise


def _initialize(*, terminal_path: Path | None, login: int | None,
                password: str | None, server: str | None):

    if terminal_path is not None:
        path = Path(terminal_path).expanduser().resolve()
        if not path.is_file():
            logger.error("MT5 terminal path does not exist: {}", path)
            return False
        initialized = mt5.initialize(str(path))
    else:
        initialized = mt5.initialize()

    if initialized is not True:
        logger.error("MT5 connection failed")
        return False

    if login is not None and mt5.login(login, password=password, server=server) is not True:
        logger.error("MT5 account login failed for account {}", login)
        mt5.shutdown()
        return False

    logger.info("MT5 connection successful")
    return True


def disconnect(_session_owner: object = _LEGACY_SESSION_OWNER) -> bool:
    """Shut down the MT5 terminal and release the process-global session.

    Only the current session owner may call this.  If a different owner
    (e.g. an MT5Gateway) holds the session, this call is a no-op so that
    legacy helpers cannot forcibly revoke an active gateway session.
    """
    released = mt5_session.release(_session_owner, shutdown_callback=mt5.shutdown)
    if released:
        logger.info("MT5 disconnected")
    else:
        logger.debug("MT5 disconnect ignored — caller does not own the session")
    return released
