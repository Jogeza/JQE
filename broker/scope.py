"""Runtime broker-scope guard for the currently authorized live deployment."""

from __future__ import annotations

from core.exceptions import ConfigurationError


WELTRADE_BROKERS = frozenset({"weltrade", "weltrade_demo"})


def enforce_weltrade_only(*, broker: str, market_data_source: str | None = None) -> None:
    """Fail closed before live execution or observation can use another broker."""
    normalized = str(broker).strip().lower()
    if normalized not in WELTRADE_BROKERS:
        raise ConfigurationError(
            f"Weltrade-only live scope rejects broker '{normalized or 'UNSET'}'"
        )
    if market_data_source is not None and market_data_source != "broker":
        raise ConfigurationError(
            "Weltrade-only live scope requires broker market data"
        )
