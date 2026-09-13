"""Application execution remains simulation-only after path consolidation."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

import main
from config import settings
from core.exceptions import ConfigurationError


@pytest.fixture(autouse=True)
def _restore_broker():
    original = settings.broker
    yield
    settings.broker = original


@pytest.mark.asyncio
@pytest.mark.parametrize("broker", ["deriv"])
async def test_non_simulation_application_execution_is_rejected_before_gateway(
    broker: str,
) -> None:
    settings.broker = broker
    with patch("main.get_gateway") as get_gateway:
        with pytest.raises(ConfigurationError, match="simulation only"):
            await main.run()
    get_gateway.assert_not_called()


def test_non_simulation_rejection_has_no_network_side_effects() -> None:
    settings.broker = "deriv"
    with patch(
        "broker.deriv_gateway.websockets.connect",
        side_effect=AssertionError("network access is forbidden"),
    ) as websocket_connect, patch(
        "broker.deriv_auth.urlopen",
        side_effect=AssertionError("network access is forbidden"),
    ) as urlopen:
        with pytest.raises(ConfigurationError, match="simulation only"):
            asyncio.run(main.run())
    websocket_connect.assert_not_called()
    urlopen.assert_not_called()
