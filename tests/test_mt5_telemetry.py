"""Tests for the capability-restricted isolated MT5 observation adapter."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from broker.mt5_telemetry import verified_demo_mt5_telemetry
from config.settings import Settings
from core.exceptions import BrokerConnectionError


def _settings(tmp_path: Path) -> Settings:
    profile = tmp_path / "mt5-daemon-profile"
    profile.mkdir()
    (profile / "terminal64.exe").touch()
    return Settings(
        _env_file=None,
        mt5_expected_environment="demo",
        observation_mt5_terminal_path=profile / "terminal64.exe",
        observation_mt5_portable_data_path=profile,
    )


@pytest.mark.asyncio
async def test_observation_connection_uses_configured_portable_profile(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    account = SimpleNamespace(login=42, trade_mode=0, server="Deriv-Demo")
    terminal = SimpleNamespace(
        data_path=str(settings.observation_mt5_portable_data_path),
        connected=True,
        trade_allowed=True,
        tradeapi_disabled=False,
    )
    with (
        patch("broker.mt5_telemetry.mt5.initialize", return_value=True) as initialize,
        patch("broker.mt5_telemetry.mt5.terminal_info", return_value=terminal),
        patch("broker.mt5_telemetry.mt5.account_info", return_value=account),
        patch("broker.mt5_demo.DemoOnlyGuard.assert_demo_account"),
    ):
        telemetry = verified_demo_mt5_telemetry(settings)
        await telemetry.connect()
        initialize.assert_called_once_with(
            str(settings.observation_mt5_terminal_path.resolve()), portable=True
        )
        await telemetry.disconnect()


@pytest.mark.asyncio
async def test_observation_connection_rejects_nonportable_data_path(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    terminal = SimpleNamespace(data_path=str(tmp_path / "shared-profile"))
    with (
        patch("broker.mt5_telemetry.mt5.initialize", return_value=True),
        patch("broker.mt5_telemetry.mt5.terminal_info", return_value=terminal),
        patch("broker.mt5_telemetry.mt5.shutdown") as shutdown,
    ):
        telemetry = verified_demo_mt5_telemetry(settings)
        with pytest.raises(BrokerConnectionError, match="did not use"):
            await telemetry.connect()
        shutdown.assert_awaited_once() if isinstance(shutdown, AsyncMock) else shutdown.assert_called_once()


def test_observation_profile_paths_are_mandatory() -> None:
    settings = Settings(_env_file=None, mt5_expected_environment="demo")
    with pytest.raises(ValueError, match="isolated MT5 terminal path"):
        verified_demo_mt5_telemetry(settings)
