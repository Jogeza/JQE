"""Tests for broker.factory.get_gateway — broker selection by configuration."""

from __future__ import annotations

import pytest

from broker.deriv_gateway import DerivGateway
from broker.factory import get_gateway
from broker.mt5_gateway import MT5Gateway
from broker.simulation_gateway import SimulationGateway
from broker.weltrade_gateway import WeltradeGateway
from config.settings import Settings
from core.exceptions import ConfigurationError


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)


class TestGetGateway:
    def test_defaults_to_mt5_without_persisted_selection(self) -> None:
        gateway = get_gateway(_settings())
        assert isinstance(gateway, MT5Gateway)

    def test_explicit_simulation_returns_simulation_gateway(self) -> None:
        gateway = get_gateway(_settings(broker="simulation"))
        assert isinstance(gateway, SimulationGateway)

    def test_simulation_uses_configured_account_balance(self) -> None:
        gateway = get_gateway(_settings(broker="simulation", account_balance=2500.0))
        assert isinstance(gateway, SimulationGateway)
        assert gateway.starting_balance == 2500.0

    def test_mt5_broker_returns_mt5_gateway(self) -> None:
        gateway = get_gateway(_settings(broker="mt5"))
        assert isinstance(gateway, MT5Gateway)

    def test_weltrade_demo_returns_weltrade_gateway(self, tmp_path) -> None:
        terminal = tmp_path / "terminal64.exe"
        terminal.touch()
        gateway = get_gateway(_settings(
            broker="weltrade_demo", weltrade_terminal_path=terminal,
            weltrade_login=42, weltrade_server="Weltrade-Demo",
        ))
        assert isinstance(gateway, WeltradeGateway)

    def test_weltrade_requires_exact_terminal_and_account_identity(self) -> None:
        with pytest.raises(ConfigurationError, match="TERMINAL_PATH"):
            get_gateway(_settings(broker="weltrade_demo"))

    def test_deriv_broker_returns_deriv_gateway(self) -> None:
        gateway = get_gateway(_settings(broker="deriv", deriv_api_token="test-token", deriv_options_account_id="CR1", deriv_expected_environment="demo"))
        assert isinstance(gateway, DerivGateway)

    def test_live_execution_scope_rejects_deriv_before_gateway_construction(self, tmp_path) -> None:
        with pytest.raises(ConfigurationError, match="Weltrade-only"):
            get_gateway(_settings(
                broker="deriv",
                broker_execution_enabled=True,
                market_data_source="broker",
                broker_selection_store_path=tmp_path / "selection.sqlite3",
                deriv_api_token="test-token",
                deriv_options_account_id="CR1",
                deriv_expected_environment="demo",
            ))

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
                deriv_options_account_id="CR1",
                deriv_expected_environment="demo",
            )
        )
        assert isinstance(gateway, DerivGateway)
        assert gateway.app_id == "9999"
        assert gateway.endpoint == "wss://example.test/v3"

    @pytest.mark.parametrize("environment", [None, "real"])
    def test_deriv_requires_explicit_demo_environment(self, environment) -> None:
        with pytest.raises(ConfigurationError, match="EXPECTED_ENVIRONMENT=demo"):
            get_gateway(_settings(broker="deriv", deriv_api_token="test-token", deriv_expected_environment=environment))

    def test_deriv_requires_exact_account_identity(self) -> None:
        with pytest.raises(ConfigurationError, match="OPTIONS_ACCOUNT_ID"):
            get_gateway(_settings(broker="deriv", deriv_api_token="test-token", deriv_expected_environment="demo"))
