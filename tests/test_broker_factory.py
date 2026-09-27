"""Production factory and config accept only the Weltrade terminal integration."""
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from broker.factory import get_gateway
from broker.weltrade_gateway import WeltradeGateway
from config.settings import Settings
from core.exceptions import ConfigurationError


@pytest.mark.parametrize('broker', ['simulation', 'deriv', 'deriv_demo', 'mt5', 'mt5_demo', 'unknown'])
def test_settings_reject_other_brokers(broker):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, broker=broker)


@pytest.mark.parametrize('broker', ['simulation', 'deriv', 'mt5', 'unknown'])
def test_factory_rejects_unvalidated_other_brokers(broker):
    with pytest.raises(ConfigurationError, match='Weltrade-only'):
        get_gateway(SimpleNamespace(broker=broker, effective_broker=broker, broker_execution_enabled=False))


def test_default_is_weltrade_and_terminal_market_data(monkeypatch):
    monkeypatch.delenv('JQE_BROKER', raising=False)
    monkeypatch.delenv('JQE_MARKET_DATA_SOURCE', raising=False)
    cfg = Settings(_env_file=None)
    assert cfg.broker == 'weltrade'
    assert cfg.market_data_source == 'broker'


@pytest.mark.parametrize('source', ['simulation', 'deriv_public'])
def test_settings_reject_cross_broker_or_generated_market_data(source):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, market_data_source=source)


@pytest.mark.parametrize('broker', ['weltrade', 'weltrade_demo'])
def test_factory_pins_weltrade_terminal_and_demo_account(tmp_path, broker):
    terminal = tmp_path / 'terminal64.exe'
    terminal.touch()
    cfg = Settings(_env_file=None, broker=broker, weltrade_terminal_path=terminal,
                   weltrade_login=42, weltrade_password='fixture', weltrade_server='Weltrade-Demo')
    gateway = get_gateway(cfg)
    assert isinstance(gateway, WeltradeGateway)
    assert gateway.login == 42
    assert gateway.server == 'Weltrade-Demo'
    assert gateway.expected_environment == 'demo'
    assert gateway.strict_lifecycle is True
    assert gateway.is_connected is False


def test_factory_requires_terminal_identity():
    with pytest.raises(ConfigurationError, match='TERMINAL_PATH'):
        get_gateway(Settings(_env_file=None, weltrade_terminal_path=None))
