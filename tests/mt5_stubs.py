"""Valid offline session fixtures for MT5 adapter tests."""

from unittest.mock import MagicMock

from core.mt5_session import mt5_session


def configure_sdk(sdk) -> None:
    """Fill only unspecified mock fields with explicit, valid DEMO facts."""
    account = sdk.account_info.return_value
    terminal = sdk.terminal_info.return_value
    for target, values in (
        (account, {"login": 12345, "server": "DemoServer", "trade_mode": 0}),
        (terminal, {"connected": True, "trade_allowed": True, "tradeapi_disabled": False}),
    ):
        if isinstance(target, MagicMock):
            for name, value in values.items():
                if name not in vars(target) and name not in target._mock_children:
                    setattr(target, name, value)


def activate_gateway(gateway) -> None:
    """Reserve an offline session for tests of methods below connection setup."""
    assert mt5_session.reserve(gateway._session_owner)
    mt5_session.activate(gateway._session_owner)


def release_gateway(gateway) -> None:
    if mt5_session.owns(gateway._session_owner):
        mt5_session.invalidate()
