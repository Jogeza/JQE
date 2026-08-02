"""Centralized exception hierarchy for the JQE Trading Platform.

Every platform-specific error inherits from :class:`JQEError`, so calling
code can catch platform errors broadly (``except JQEError``) at a
composition boundary (e.g. the main loop, an API endpoint) or narrowly
(e.g. ``except RiskViolationError``) where the distinction matters.

Raising one of these instead of returning a sentinel value (``None``,
``{"approved": False}``, etc.) or printing an error message keeps failure
handling explicit, typed, and consistent with structured logging: callers
log ``str(exc)`` and get full context in one place.
"""

from __future__ import annotations


class JQEError(Exception):
    """Base class for all JQE Trading Platform exceptions.

    Args:
        message: Human-readable description of the error.
        **context: Optional structured context (e.g. ``symbol="XAUUSD"``)
            rendered into the exception message, so log lines carry
            enough detail to debug without extra string formatting at
            every call site.
    """

    def __init__(self, message: str, **context: object) -> None:
        self.message = message
        self.context = context
        if context:
            rendered = ", ".join(f"{key}={value!r}" for key, value in context.items())
            message = f"{message} ({rendered})"
        super().__init__(message)


class ConfigurationError(JQEError):
    """Raised when platform configuration is missing, invalid, or inconsistent."""


class BrokerConnectionError(JQEError):
    """Raised when a connection to the trading broker (e.g. MT5) cannot be
    established, is lost, or is used while not connected."""


class MarketDataError(JQEError):
    """Raised when market data cannot be retrieved, is empty, or fails
    validation before being used downstream."""


class RiskViolationError(JQEError):
    """Raised when a proposed trade is rejected by the risk management
    engine (e.g. confidence too low, spread too wide, daily loss limit
    reached)."""


class StrategyError(JQEError):
    """Raised when strategy signal generation fails or produces output
    that downstream consumers cannot use."""


class ExecutionError(JQEError):
    """Raised when order placement, modification, or execution fails at
    the broker or simulator level."""
