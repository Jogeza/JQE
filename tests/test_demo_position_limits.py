from types import SimpleNamespace
import pytest
from execution.position_limits import demo_position_cap


@pytest.mark.parametrize("equity,currency,expected", [
    (49.99, "USD", 1), (50.0, "USD", 5), (5000.0, "USD", 5),
    (float("nan"), "USD", 1), (float("inf"), "USD", 1),
    (None, "USD", 1), (100.0, "EUR", 1), (-10.0, "USD", 1),
])
def test_cap_uses_verified_equity_floor_and_never_scales_above_five(equity, currency, expected):
    settings = SimpleNamespace(weltrade_demo_max_open_positions=5,
                               weltrade_demo_position_equity_floor_usd=50)
    assert demo_position_cap(settings, equity=equity, currency=currency) == expected


def test_unconfigured_or_invalid_cap_preserves_single_position():
    for value in [None, True, 6, 0]:
        settings = SimpleNamespace(weltrade_demo_max_open_positions=value)
        assert demo_position_cap(settings, equity=100, currency="USD") == 1
