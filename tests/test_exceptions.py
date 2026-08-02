"""Tests for core.exceptions — the platform's centralized exception hierarchy."""

from __future__ import annotations

import pytest

from core.exceptions import (
    BrokerConnectionError,
    ConfigurationError,
    ExecutionError,
    JQEError,
    MarketDataError,
    RiskViolationError,
    StrategyError,
)

ALL_SUBCLASSES = [
    ConfigurationError,
    BrokerConnectionError,
    MarketDataError,
    RiskViolationError,
    StrategyError,
    ExecutionError,
]


class TestExceptionHierarchy:
    """Every platform exception must be a JQEError, and JQEError a real Exception."""

    @pytest.mark.parametrize("exc_type", ALL_SUBCLASSES)
    def test_subclasses_inherit_from_jqe_error(self, exc_type: type[JQEError]) -> None:
        assert issubclass(exc_type, JQEError)

    def test_jqe_error_inherits_from_exception(self) -> None:
        assert issubclass(JQEError, Exception)

    @pytest.mark.parametrize("exc_type", ALL_SUBCLASSES)
    def test_can_be_raised_and_caught_as_jqe_error(self, exc_type: type[JQEError]) -> None:
        with pytest.raises(JQEError):
            raise exc_type("something went wrong")

    def test_specific_subclass_not_caught_by_sibling_type(self) -> None:
        with pytest.raises(MarketDataError):
            try:
                raise MarketDataError("bad data")
            except RiskViolationError:  # pragma: no cover - must not match
                pytest.fail("MarketDataError should not be caught as RiskViolationError")


class TestJQEErrorContext:
    """Structured context passed to JQEError should be rendered into the message."""

    def test_message_only(self) -> None:
        err = JQEError("plain message")
        assert str(err) == "plain message"
        assert err.message == "plain message"
        assert err.context == {}

    def test_message_with_context(self) -> None:
        err = MarketDataError("bad data", symbol="XAUUSD", count=0)
        rendered = str(err)
        assert "bad data" in rendered
        assert "symbol='XAUUSD'" in rendered
        assert "count=0" in rendered
        assert err.context == {"symbol": "XAUUSD", "count": 0}
