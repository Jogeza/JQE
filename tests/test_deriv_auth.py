"""Mocked Deriv PAT/OTP session tests; no network is used."""

import asyncio

import socket
import ssl
from http.client import InvalidURL
from urllib.error import HTTPError, URLError
from unittest.mock import AsyncMock

import pytest

from broker.deriv_auth import (
    DerivAuthConfig, DerivAuthErrorCode, DerivAuthFailure, DerivAuthState,
    DerivAuthFailureCategory, DerivPATOTPTransport, DerivPATOTPSession,
)


class FakeTransport:
    def __init__(self, response=None, failure=None, verified_account_id="CR1"):
        self.response = response or {"url": "wss://fake/demo", "account_id": "CR1", "environment": "demo"}
        self.failure = failure
        self.verified_account_id = verified_account_id
        self.request_otp = AsyncMock(side_effect=self._request)
        self.connect_websocket = AsyncMock(side_effect=self._connect)
        self.verify_account_identity = AsyncMock(side_effect=self._verify)

    async def _request(self, **kwargs):
        if self.failure:
            raise self.failure
        return self.response

    async def _connect(self, url, **_kwargs):
        if self.failure:
            raise self.failure

    async def _verify(self, _connection, **kwargs):
        if self.failure:
            raise self.failure
        if self.verified_account_id != kwargs["expected_account_id"]:
            raise DerivAuthFailure(DerivAuthErrorCode.ACCOUNT_MISMATCH)
        return self.verified_account_id


@pytest.mark.asyncio
async def test_valid_pat_otp_session_is_ready_without_exposing_pat():
    pat = "test-pat-token"
    session = DerivPATOTPSession(DerivAuthConfig("test-app-id", pat, "CR1", "demo"), FakeTransport())
    result = await session.connect()
    assert result.account_id == "CR1"
    assert session.is_ready
    assert pat not in repr(DerivAuthConfig("test-app-id", pat))


@pytest.mark.asyncio
@pytest.mark.parametrize("config,code", [
    (DerivAuthConfig("", "test", None, None), DerivAuthErrorCode.MISSING_APP_ID),
    (DerivAuthConfig("app", "", None, None), DerivAuthErrorCode.MISSING_TOKEN),
])
async def test_missing_configuration_fails_closed(config, code):
    session = DerivPATOTPSession(config, FakeTransport())
    with pytest.raises(DerivAuthFailure) as exc:
        await session.connect()
    assert exc.value.code is code
    assert not session.is_ready


@pytest.mark.asyncio
@pytest.mark.parametrize("error,code", [
    ("invalid_token", DerivAuthErrorCode.INVALID_TOKEN),
    ("expired_token", DerivAuthErrorCode.EXPIRED_TOKEN),
    ("revoked_token", DerivAuthErrorCode.REVOKED_TOKEN),
])
async def test_token_failures_are_typed_and_closed(error, code):
    session = DerivPATOTPSession(DerivAuthConfig("app", "test-pat", "CR1", "demo"), FakeTransport({"error": error}))
    with pytest.raises(DerivAuthFailure) as exc:
        await session.connect()
    assert exc.value.code is code
    assert "test-pat" not in str(exc.value)
    assert not session.is_ready


@pytest.mark.asyncio
@pytest.mark.parametrize("response,code", [
    ({"error": "otp"}, DerivAuthErrorCode.OTP_FAILURE),
    ({"url": "wss://fake/demo"}, DerivAuthErrorCode.MISSING_ACCOUNT_ID),
    ({"url": "wss://fake/demo", "account_id": "CR1"}, DerivAuthErrorCode.MISSING_ENVIRONMENT),
])
async def test_malformed_session_responses_fail_closed(response, code):
    session = DerivPATOTPSession(DerivAuthConfig("app", "test-pat", "CR1", "demo"), FakeTransport(response))
    with pytest.raises(DerivAuthFailure) as exc:
        await session.connect()
    assert exc.value.code is code
    assert not session.is_ready


@pytest.mark.asyncio
async def test_non_mapping_otp_response_fails_closed():
    transport = FakeTransport()
    transport.response = []
    session = DerivPATOTPSession(DerivAuthConfig("app", "test-pat", "CR1", "demo"), transport)
    with pytest.raises(DerivAuthFailure) as exc:
        await session.connect()
    assert exc.value.code is DerivAuthErrorCode.MALFORMED_OTP_RESPONSE
    assert session.state is DerivAuthState.FAILED


@pytest.mark.asyncio
async def test_account_and_environment_mismatch_fail_closed():
    for config, code in [
        (DerivAuthConfig("app", "test-pat", "OTHER", "demo"), DerivAuthErrorCode.ACCOUNT_MISMATCH),
        (DerivAuthConfig("app", "test-pat", "CR1", "real"), DerivAuthErrorCode.ENVIRONMENT_MISMATCH),
    ]:
        session = DerivPATOTPSession(config, FakeTransport())
        with pytest.raises(DerivAuthFailure) as exc:
            await session.connect()
        assert exc.value.code is code
        assert not session.is_ready


@pytest.mark.asyncio
async def test_websocket_reported_account_mismatch_fails_closed():
    transport = FakeTransport(verified_account_id="DOT99999999")
    transport.response = {
        "url": "wss://fake/demo", "account_id": "DOT90004580", "environment": "demo"
    }
    session = DerivPATOTPSession(
        DerivAuthConfig("app", "test-pat", "DOT90004580", "demo"), transport
    )
    with pytest.raises(DerivAuthFailure) as exc:
        await session.connect()
    assert exc.value.code is DerivAuthErrorCode.ACCOUNT_MISMATCH
    assert session.state is DerivAuthState.FAILED


@pytest.mark.asyncio
async def test_websocket_failure_does_not_mark_ready():
    transport = FakeTransport()
    transport.connect_websocket.side_effect = ConnectionError("socket")
    session = DerivPATOTPSession(DerivAuthConfig("app", "test-pat", "CR1", "demo"), transport)
    with pytest.raises(DerivAuthFailure) as exc:
        await session.connect()
    assert exc.value.code is DerivAuthErrorCode.WEBSOCKET_FAILURE
    assert not session.is_ready


@pytest.mark.asyncio
async def test_real_transport_uses_documented_headers_and_normalizes_otp_response():
    calls = []

    async def post(url, headers):
        calls.append((url, headers))
        return 200, {"data": {"url": "wss://api.derivws.com/trading/v1/options/ws/demo?otp=one-use"}}

    connected = []

    class Socket:
        async def send(self, raw):
            assert raw == '{"balance": 1, "req_id": 1}'

        async def recv(self):
            return '{"msg_type":"balance","req_id":1,"balance":{"loginid":"CR1"}}'

    async def connect(url, **_kwargs):
        connected.append(url)
        return Socket()

    transport = DerivPATOTPTransport(http_post=post, websocket_connect=connect)
    session = DerivPATOTPSession(
        DerivAuthConfig("app", "test-pat-token", "CR1", "demo"), transport
    )
    result = await session.connect()
    assert result.account_id == "CR1"
    assert session.state is DerivAuthState.READY
    assert calls == [(
        "https://api.derivws.com/trading/v1/options/accounts/CR1/otp",
        {"Deriv-App-ID": "app", "Authorization": "Bearer test-pat-token", "Content-Type": "application/json"},
    )]
    assert connected == [result.websocket_url]


@pytest.mark.asyncio
async def test_options_account_id_is_unchanged_and_required():
    calls = []
    async def post(url, _headers):
        calls.append(url)
        return 200, {"data": {"url": "wss://api.derivws.com/trading/v1/options/ws/demo?otp=fake"}}
    transport = DerivPATOTPTransport(http_post=post)
    result = await transport.request_otp(
        app_id="app", authorization="Bearer fake", environment="demo",
        options_account_id="DOT90004580",
    )
    assert calls == ["https://api.derivws.com/trading/v1/options/accounts/DOT90004580/otp"]
    assert result["account_id"] == "DOT90004580"
    with pytest.raises(DerivAuthFailure) as exc:
        await transport.request_otp(app_id="app", authorization="Bearer fake", environment="demo", options_account_id="")
    assert exc.value.code is DerivAuthErrorCode.MISSING_ACCOUNT_ID


def test_legacy_expected_account_setting_is_not_active():
    from config.settings import Settings
    assert "deriv_expected_account" not in Settings.model_fields
    assert "deriv_options_account_id" in Settings.model_fields


@pytest.mark.asyncio
@pytest.mark.parametrize("status,code", [
    (401, DerivAuthErrorCode.HTTP_FAILURE),
    (403, DerivAuthErrorCode.HTTP_FAILURE),
    (400, DerivAuthErrorCode.HTTP_FAILURE),
    (404, DerivAuthErrorCode.HTTP_FAILURE),
    (429, DerivAuthErrorCode.HTTP_FAILURE),
    (500, DerivAuthErrorCode.HTTP_FAILURE),
    (502, DerivAuthErrorCode.HTTP_FAILURE),
    (503, DerivAuthErrorCode.HTTP_FAILURE),
    (504, DerivAuthErrorCode.HTTP_FAILURE),
])
async def test_real_transport_http_failures_fail_closed(status, code):
    async def post(_url, _headers):
        return status, {}

    transport = DerivPATOTPTransport(http_post=post)
    with pytest.raises(DerivAuthFailure) as exc:
        await transport.request_otp(
            app_id="app", authorization="Bearer test-pat-token",
            environment="demo", options_account_id="DOT90004580",
        )
    assert exc.value.code is code
    assert exc.value.http_status == status


@pytest.mark.asyncio
async def test_real_transport_rejects_invalid_session_url_without_connecting():
    connected = False

    async def post(_url, _headers):
        return 200, {"data": {"url": "https://not-websocket"}}

    async def connect(_url):
        nonlocal connected
        connected = True

    transport = DerivPATOTPTransport(http_post=post, websocket_connect=connect)
    with pytest.raises(DerivAuthFailure) as exc:
        await transport.request_otp(
            app_id="app", authorization="Bearer test-pat-token",
            environment="demo", options_account_id="DOT90004580",
        )
    assert exc.value.code is DerivAuthErrorCode.INVALID_SESSION_URL
    assert not connected


@pytest.mark.asyncio
@pytest.mark.parametrize("url", [
    "wss://api.derivws.com/trading/v1/options/ws/demo",
    "wss://api.derivws.com/trading/v1/options/ws/real?otp=x",
    "wss://evil.example/trading/v1/options/ws/demo?otp=x",
    "wss://ws.derivws.com/websockets/v3?otp=x",
])
async def test_real_transport_rejects_non_documented_demo_urls(url):
    async def post(_url, _headers):
        return 200, {"data": {"url": url}}

    transport = DerivPATOTPTransport(http_post=post)
    with pytest.raises(DerivAuthFailure) as exc:
        await transport.request_otp(app_id="app", authorization="Bearer fake", environment="demo", options_account_id="DOT90004580")
    assert exc.value.code is DerivAuthErrorCode.INVALID_SESSION_URL


@pytest.mark.asyncio
async def test_websocket_connector_receives_app_id_header_value():
    captured = {}
    async def connect(url, **kwargs):
        captured.update(url=url, kwargs=kwargs)
        return object()
    transport = DerivPATOTPTransport(websocket_connect=connect)
    await transport.connect_websocket("wss://api.derivws.com/trading/v1/options/ws/demo?otp=fake", app_id="app")
    assert captured["kwargs"] == {"app_id": "app"}


class ScriptedSocket:
    def __init__(self, messages):
        self.messages = iter(messages)
        self.sent = []

    async def send(self, raw):
        self.sent.append(raw)

    async def recv(self):
        message = next(self.messages)
        if isinstance(message, BaseException):
            raise message
        return message


@pytest.mark.asyncio
async def test_identity_verification_exact_match_and_skips_unrelated_message():
    socket = ScriptedSocket([
        '{"msg_type":"tick","req_id":99}',
        '{"msg_type":"balance","req_id":1,"balance":{"loginid":"DOT90004580"}}',
    ])
    result = await DerivPATOTPTransport().verify_account_identity(
        socket, expected_account_id="DOT90004580", timeout_seconds=1
    )
    assert result == "DOT90004580"
    assert socket.sent == ['{"balance": 1, "req_id": 1}']


@pytest.mark.asyncio
@pytest.mark.parametrize("message,code", [
    ('{"msg_type":"balance","req_id":1,"balance":{"loginid":"DOT99999999"}}', DerivAuthErrorCode.ACCOUNT_MISMATCH),
    ('{"msg_type":"balance","req_id":1,"balance":{}}', DerivAuthErrorCode.MALFORMED_ACCOUNT_RESPONSE),
    ('{"msg_type":"balance","req_id":1,"balance":{"loginid":""}}', DerivAuthErrorCode.MALFORMED_ACCOUNT_RESPONSE),
    ('{"msg_type":"balance","req_id":1}', DerivAuthErrorCode.MALFORMED_ACCOUNT_RESPONSE),
    ('{"msg_type":"tick","req_id":1,"balance":{"loginid":"DOT90004580"}}', DerivAuthErrorCode.MALFORMED_ACCOUNT_RESPONSE),
    ('{"req_id":1,"error":{"code":"AuthorizationRequired"}}', DerivAuthErrorCode.ACCOUNT_IDENTITY_FAILURE),
])
async def test_identity_verification_failures_are_typed(message, code):
    with pytest.raises(DerivAuthFailure) as exc:
        await DerivPATOTPTransport().verify_account_identity(
            ScriptedSocket([message]), expected_account_id="DOT90004580", timeout_seconds=1
        )
    assert exc.value.code is code


@pytest.mark.asyncio
async def test_identity_verification_timeout_is_typed():
    class SlowSocket:
        async def send(self, _raw):
            return None

        async def recv(self):
            await asyncio.sleep(1)

    with pytest.raises(DerivAuthFailure) as exc:
        await DerivPATOTPTransport().verify_account_identity(
            SlowSocket(), expected_account_id="DOT90004580", timeout_seconds=0.01
        )
    assert exc.value.code is DerivAuthErrorCode.ACCOUNT_IDENTITY_TIMEOUT


@pytest.mark.asyncio
@pytest.mark.parametrize("payload,code", [
    ({"errors": [{"message": "secret-pat-token"}]}, DerivAuthErrorCode.OTP_FAILURE),
    ({}, DerivAuthErrorCode.MALFORMED_OTP_RESPONSE),
    ({"data": {}}, DerivAuthErrorCode.INVALID_SESSION_URL),
])
async def test_malformed_or_error_payloads_are_safe(payload, code):
    async def post(_url, _headers):
        return 200, payload

    transport = DerivPATOTPTransport(http_post=post)
    with pytest.raises(DerivAuthFailure) as exc:
        await transport.request_otp(
            app_id="app", authorization="Bearer secret-pat-token",
            environment="demo", options_account_id="DOT90004580",
        )
    assert exc.value.code is code
    assert "secret-pat-token" not in str(exc.value)
    assert exc.value.http_status is None


@pytest.mark.asyncio
async def test_transport_connection_failure_is_safe_and_has_no_status():
    async def post(_url, _headers):
        return 200, {"data": {"url": "wss://api.derivws.com/trading/v1/options/ws/demo?otp=x"}}

    async def connect(_url):
        raise TimeoutError("secret-pat-token")

    transport = DerivPATOTPTransport(http_post=post, websocket_connect=connect)
    with pytest.raises(DerivAuthFailure) as exc:
        await transport.connect_websocket("wss://api.derivws.com/trading/v1/options/ws/demo?otp=x")
    assert exc.value.code is DerivAuthErrorCode.WEBSOCKET_FAILURE
    assert exc.value.http_status is None
    assert "secret-pat-token" not in str(exc.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure,category", [
    (socket.gaierror("secret-pat-token"), DerivAuthFailureCategory.NETWORK_DNS_FAILURE),
    (ConnectionError("secret-pat-token"), DerivAuthFailureCategory.NETWORK_CONNECTION_FAILURE),
    (TimeoutError("secret-pat-token"), DerivAuthFailureCategory.NETWORK_TIMEOUT),
    (ssl.SSLError("secret-pat-token"), DerivAuthFailureCategory.NETWORK_TLS_FAILURE),
])
async def test_network_failures_are_safely_categorized_without_status(failure, category):
    async def post(_url, _headers):
        raise failure
    transport = DerivPATOTPTransport(http_post=post)
    with pytest.raises(DerivAuthFailure) as exc:
        await transport.request_otp(app_id="app", authorization="Bearer secret-pat-token", environment="demo", options_account_id="DOT90004580")
    assert exc.value.code is DerivAuthErrorCode.HTTP_FAILURE
    assert exc.value.http_status is None
    assert exc.value.category is category
    assert "secret-pat-token" not in str(exc.value)


@pytest.mark.asyncio
async def test_injected_http_error_preserves_status():
    async def post(_url, _headers):
        raise HTTPError("https://api.derivws.com", 503, "secret", {}, None)
    with pytest.raises(DerivAuthFailure) as exc:
        await DerivPATOTPTransport(http_post=post).request_otp(
            app_id="app", authorization="Bearer secret-pat-token",
            environment="demo", options_account_id="DOT90004580",
        )
    assert exc.value.code is DerivAuthErrorCode.HTTP_FAILURE
    assert exc.value.http_status == 503
    assert exc.value.category is None
    assert "secret" not in str(exc.value)


@pytest.mark.asyncio
async def test_url_error_is_classified_without_exposing_reason():
    async def post(_url, _headers):
        raise URLError("secret-pat-token")
    with pytest.raises(DerivAuthFailure) as exc:
        await DerivPATOTPTransport(http_post=post).request_otp(
            app_id="app", authorization="Bearer secret-pat-token",
            environment="demo", options_account_id="DOT90004580",
        )
    assert exc.value.category is DerivAuthFailureCategory.NETWORK_URL_FAILURE
    assert exc.value.http_status is None
    assert "secret-pat-token" not in str(exc.value)


@pytest.mark.asyncio
async def test_unknown_exception_is_classified_safely():
    async def post(_url, _headers):
        raise RuntimeError("secret-pat-token")
    with pytest.raises(DerivAuthFailure) as exc:
        await DerivPATOTPTransport(http_post=post).request_otp(
            app_id="app", authorization="Bearer secret-pat-token",
            environment="demo", options_account_id="DOT90004580",
        )
    assert exc.value.category is DerivAuthFailureCategory.NETWORK_UNKNOWN_FAILURE
    assert "secret-pat-token" not in str(exc.value)


@pytest.mark.asyncio
async def test_invalid_url_from_embedded_account_whitespace_is_url_failure():
    async def post(url, _headers):
        if " " in url:
            raise InvalidURL("secret-pat-token")
        raise AssertionError("expected malformed URL")
    with pytest.raises(DerivAuthFailure) as exc:
        await DerivPATOTPTransport(http_post=post).request_otp(
            app_id="app", authorization="Bearer secret-pat-token",
            environment="demo", options_account_id="DOT 90004580",
        )
    assert exc.value.category is DerivAuthFailureCategory.NETWORK_URL_FAILURE
    assert exc.value.http_status is None
    assert "secret-pat-token" not in str(exc.value)


@pytest.mark.asyncio
async def test_session_close_and_expiry_clear_readiness():
    transport = FakeTransport()
    session = DerivPATOTPSession(DerivAuthConfig("app", "test-pat", "CR1", "demo"), transport)
    await session.connect()
    session.mark_expired()
    assert not session.is_ready
    assert session.state is DerivAuthState.FAILED
    await session.connect()
    await session.close()
    assert not session.is_ready
    assert session.state is DerivAuthState.CLOSED
