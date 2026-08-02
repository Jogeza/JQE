"""Tests for broker.factory.get_gateway — broker selection by configuration."""

from __future__ import annotations

import pytest

from broker.deriv_gateway import DerivGateway
from broker.factory import get_gateway
from broker.mt5_gateway import MT5Gateway
from broker.simulation_gateway import SimulationGateway
from config.settings import Settings
from core.exceptions import ConfigurationError


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)


class TestGetGateway:
    def test_defaults_to_simulation(self) -> None:
        gateway = get_gateway(_settings())
        assert isinstance(gateway, SimulationGateway)

    def test_simulation_uses_configured_account_balance(self) -> None:
        gateway = get_gateway(_settings(account_balance=2500.0))
        assert isinstance(gateway, SimulationGateway)
        assert gateway.starting_balance == 2500.0

    def test_mt5_broker_returns_mt5_gateway(self) -> None:
        gateway = get_gateway(_settings(broker="mt5"))
        assert isinstance(gateway, MT5Gateway)

    def test_deriv_broker_returns_deriv_gateway(self) -> None:
        gateway = get_gateway(_settings(broker="deriv", deriv_api_token="test-token"))
        assert isinstance(gateway, DerivGateway)

    def test_deriv_broker_without_token_raises(self) -> None:
        with pytest.raises(ConfigurationError):
            get_gateway(_settings(broker="deriv", deriv_api_token=None))

    def test_deriv_gateway_uses_configured_app_id_and_endpoint(self) -> None:
        gateway = get_gateway(
            _settings(
                broker="deriv",
                deriv_api_token="test-token",
                deriv_app_id="9999",
                deriv_endpoint="wss://example.test/v3",
            )
        )
        assert isinstance(gateway, DerivGateway)
        assert gateway.app_id == "9999"
        assert gateway.endpoint == "wss://example.test/v3"
