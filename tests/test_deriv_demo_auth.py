"""Offline tests for the isolated Deriv demo authentication harness."""

import pytest

from broker.deriv_auth import DerivAuthConfig, DerivAuthFailure, DerivAuthErrorCode
from config.settings import Settings
from tools.deriv_demo_auth import run_authentication


class FakeTransport:
    def __init__(self, failure=None):
        self.calls = 0
        self.failure = failure

    async def request_otp(self, **_kwargs):
        self.calls += 1
        if self.failure:
            raise self.failure
        return {"url": "wss://api.derivws.com/trading/v1/options/ws/demo?otp=fake", "account_id": "DOT90004580", "environment": "demo"}

    async def connect_websocket(self, _url, **_kwargs):
        self.calls += 1
        return object()

    async def verify_account_identity(self, _connection, **_kwargs):
        self.calls += 1
        return "DOT90004580"


def settings() -> Settings:
    return Settings(
        deriv_app_id="app", deriv_api_token="test-pat-token",
        deriv_options_account_id="DOT90004580", deriv_expected_environment="demo",
    )


@pytest.mark.asyncio
async def test_missing_configuration_stops_before_transport():
    transport = FakeTransport()
    result = await run_authentication(settings=Settings(deriv_app_id="app", deriv_api_token="test-pat-token", deriv_options_account_id=None, deriv_expected_environment="demo"), transport=transport, emit=lambda _: None)
    assert result == 2
    assert transport.calls == 0


@pytest.mark.asyncio
async def test_non_demo_stops_before_transport():
    transport = FakeTransport()
    result = await run_authentication(settings=Settings(deriv_app_id="app", deriv_api_token="test-pat-token", deriv_options_account_id="DOT90004580", deriv_expected_environment="real"), transport=transport, emit=lambda _: None)
    assert result == 2
    assert transport.calls == 0


@pytest.mark.asyncio
async def test_authentication_failure_is_safe_and_single_shot():
    transport = FakeTransport(DerivAuthFailure(DerivAuthErrorCode.HTTP_FAILURE, http_status=404))
    output = []
    result = await run_authentication(settings=settings(), transport=transport, emit=output.append)
    assert result == 1
    assert transport.calls == 1
    joined = "\n".join(output)
    assert "test-pat-token" not in joined
    assert "otp=fake" not in joined
    assert "HTTP_STATUS=404" in joined
    assert "FAILURE_CATEGORY=none" in joined


@pytest.mark.asyncio
async def test_transport_failure_without_http_status_reports_none():
    transport = FakeTransport(DerivAuthFailure(DerivAuthErrorCode.WEBSOCKET_FAILURE))
    output = []
    result = await run_authentication(settings=settings(), transport=transport, emit=output.append)
    assert result == 1
    assert "HTTP_STATUS=none" in output
    assert "FAILURE_CATEGORY=none" in output
    assert "test-pat-token" not in "\n".join(output)


@pytest.mark.asyncio
async def test_success_closes_session_without_trading_imports():
    transport = FakeTransport()
    output = []
    result = await run_authentication(settings=settings(), transport=transport, emit=output.append)
    assert result == 0
    assert transport.calls == 3
    assert "SESSION_CLOSED=true" in output
    assert "ACCOUNT_IDENTITY=WEBSOCKET_VERIFIED" in output
    assert "WEBSOCKET_ACCOUNT_ID=DOT90004580" in output
    assert not any("AUTHORIZATION" in line or "test-pat-token" in line for line in output)
