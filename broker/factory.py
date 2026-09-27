"""Selects and constructs the configured :class:`~broker.base.BrokerGateway`.

This is the single place that knows how to turn ``settings.broker``
into a concrete gateway instance. Callers (``main.py``, future API
endpoints, tests) depend on :func:`get_gateway`, never on a concrete
gateway class directly — that keeps broker selection a configuration
concern, not a code-path concern.
"""

from __future__ import annotations

from broker.base import BrokerGateway
from broker.weltrade_gateway import WeltradeGateway
from broker.scope import enforce_weltrade_only
from config import Settings
from config import settings as default_settings
from core.exceptions import ConfigurationError


def get_gateway(settings: Settings | None = None) -> BrokerGateway:
    """Constructs the Weltrade :class:`~broker.base.BrokerGateway`.

    Weltrade is the only supported broker. Any other configured or persisted
    broker fails closed here rather than constructing a gateway.

    Args:
        settings: Settings to read the Weltrade identity fields from.
            Defaults to the shared :data:`config.settings` instance.

    Returns:
        A Weltrade gateway instance. Not yet connected — callers are
        responsible for ``await gateway.connect()`` (or using it as an
        ``async with`` context manager).

    Raises:
        core.exceptions.ConfigurationError: If the effective broker is not
            Weltrade, or required Weltrade configuration is missing.
    """
    settings = settings or default_settings
    effective_broker = getattr(settings, "effective_broker", settings.broker)
    enforce_weltrade_only(
        broker=effective_broker,
        market_data_source=getattr(settings, "market_data_source", None)
        if getattr(settings, "broker_execution_enabled", False) else None,
    )

    if effective_broker in ("weltrade", "weltrade_demo"):
        if not settings.weltrade_terminal_path:
            raise ConfigurationError("JQE_WELTRADE_TERMINAL_PATH is required for Weltrade")
        login = settings.effective_weltrade_login
        server = settings.effective_weltrade_server
        password = settings.effective_weltrade_password
        if not login or not server:
            raise ConfigurationError("Weltrade demo login and server identity are required")
        return WeltradeGateway(
            terminal_path=settings.weltrade_terminal_path,
            login=login,
            password=password,
            server=server,
            expected_environment="demo",
            strict_lifecycle=True,
        )

    raise ConfigurationError(f"Unknown broker: {effective_broker!r}")
