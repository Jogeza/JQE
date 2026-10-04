"""Pure account-evidence position cap; never authorizes an order."""
import math


def demo_position_cap(settings, *, equity, currency):
    limit = getattr(settings, "weltrade_demo_max_open_positions", 1)
    floor = getattr(settings, "weltrade_demo_position_equity_floor_usd", 50.0)
    if (not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 5
            or not isinstance(floor, (int, float)) or not math.isfinite(floor) or floor < 50):
        return 1
    if (currency != "USD" or not isinstance(equity, (int, float))
            or isinstance(equity, bool) or not math.isfinite(equity) or equity < floor):
        return 1
    return limit
