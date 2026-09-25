"""Selects and constructs the configured :class:`~broker.base.BrokerGateway`.

This is the single place that knows how to turn ``settings.broker``
into a concrete gateway instance. Callers (``main.py``, future API
endpoints, tests) depend on :func:`get_gateway`, never on a concrete
gateway class directly — that keeps broker selection a configuration
concern, not a code-path concern.
"""

from __future__ import annotations

from broker.base import BrokerGateway
from broker.deriv_auth import DerivAuthConfig, DerivPATOTPSession, DerivPATOTPTransport
from broker.deriv_demo import DerivDemoGateway
from broker.deriv_gateway import DerivGateway
from broker.mt5_demo import MT5DemoGateway
from broker.mt5_gateway import MT5Gateway
from broker.simulation_gateway import SimulationGateway
from broker.weltrade_gateway import WeltradeGateway
from broker.scope import enforce_weltrade_only
from config import Settings
from config import settings as default_settings
from core.exceptions import ConfigurationError


def get_gateway(settings: Settings | None = None) -> BrokerGateway:
    """Constructs the ``BrokerGateway`` implementation selected by configuration.

    Args:
        settings: Settings to read ``broker`` (and, for Deriv, the
            ``deriv_*`` fields) from. Defaults to the shared
            :data:`config.settings` instance.

    Returns:
        A gateway instance. Not yet connected — callers are
        responsible for ``await gateway.connect()`` (or using it as an
        ``async with`` context manager).

    Raises:
        core.exceptions.ConfigurationError: If ``settings.broker`` is
            unrecognized, or required broker-specific configuration
            (e.g. a Deriv API token) is missing.
    """
    settings = settings or default_settings
    effective_broker = getattr(settings, "effective_broker", settings.broker)
    if getattr(settings, "broker_execution_enabled", False):
        enforce_weltrade_only(
            broker=effective_broker,
            market_data_source=getattr(settings, "market_data_source", None),
        )

    if effective_broker == "simulation":
        return SimulationGateway(starting_balance=settings.account_balance)

    if effective_broker in ("deriv", "deriv_demo"):
        if not settings.deriv_api_token:
            raise ConfigurationError("JQE_DERIV_API_TOKEN is required when JQE_BROKER=deriv")
        if settings.deriv_expected_environment != "demo":
            raise ConfigurationError(
                "JQE_DERIV_EXPECTED_ENVIRONMENT=demo is required for Deriv read-only access"
            )
        if not settings.deriv_options_account_id:
            raise ConfigurationError(
                "JQE_DERIV_OPTIONS_ACCOUNT_ID is required for exact Deriv DEMO identity verification"
            )
        auth_session = DerivPATOTPSession(
            DerivAuthConfig(
                app_id=settings.deriv_app_id,
                pat=settings.deriv_api_token,
                options_account_id=settings.deriv_options_account_id,
                expected_environment="demo",
            ),
            DerivPATOTPTransport(),
        )
        return DerivDemoGateway(
            api_token=settings.deriv_api_token,
            app_id=settings.deriv_app_id,
            endpoint=settings.deriv_endpoint,
            expected_environment="demo",
            auth_session=auth_session,
        )

    if effective_broker in ("mt5", "mt5_demo"):
        if settings.mt5_expected_environment is not None and settings.mt5_expected_environment != "demo":
            raise ConfigurationError(
                "Live/real MT5 execution is prohibited; expected_environment must be 'demo'"
            )
        return MT5DemoGateway(
            terminal_path=settings.mt5_terminal_path,
            login=settings.mt5_login,
            password=settings.mt5_password,
            server=settings.mt5_server,
            expected_environment="demo",
            strict_lifecycle=settings.environment == "production",
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
