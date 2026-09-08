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
from broker.deriv_gateway import DerivGateway
from broker.mt5_gateway import MT5Gateway
from broker.simulation_gateway import SimulationGateway
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

    if settings.broker == "simulation":
        return SimulationGateway(starting_balance=settings.account_balance)

    if settings.broker == "deriv":
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
        return DerivGateway(
            api_token=settings.deriv_api_token,
            app_id=settings.deriv_app_id,
            endpoint=settings.deriv_endpoint,
            expected_environment=settings.deriv_expected_environment,
            auth_session=auth_session,
        )

    if settings.broker == "mt5":
        return MT5Gateway(
            terminal_path=settings.mt5_terminal_path,
            login=settings.mt5_login,
            password=settings.mt5_password,
            server=settings.mt5_server,
            expected_environment=settings.mt5_expected_environment,
            strict_lifecycle=settings.environment == "production",
        )

    raise ConfigurationError(f"Unknown broker: {settings.broker!r}")
