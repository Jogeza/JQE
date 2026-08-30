"""Offline regression: the legacy manager must never reach MT5."""

from unittest.mock import patch

import pytest

from core.exceptions import ConfigurationError
from execution.order_manager import OrderManager


def test_legacy_manager_refuses_mt5_before_gateway_construction() -> None:
    with patch("execution.order_manager.settings.broker", "mt5"), patch(
        "execution.order_manager.get_gateway"
    ) as get_gateway:
        with pytest.raises(ConfigurationError, match="canonical durable executor"):
            OrderManager()

    get_gateway.assert_not_called()
