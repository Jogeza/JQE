"""Selects and constructs the configured :class:`~broker.base.BrokerGateway`.

This is the single place that knows how to turn ``settings.broker``
into a concrete gateway instance. Callers (``main.py``, future API
endpoints, tests) depend on :func:`get_gateway`, never on a concrete
gateway class directly — that keeps broker selection a configuration
concern, not a code-path concern.
"""

from __future__ import annotations

from broker.base import BrokerGateway
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
        return DerivGateway(
            api_token=settings.deriv_api_token,
            app_id=settings.deriv_app_id,
            endpoint=settings.deriv_endpoint,
        )

    if settings.broker == "mt5":
        return MT5Gateway()

    raise ConfigurationError(f"Unknown broker: {settings.broker!r}")
