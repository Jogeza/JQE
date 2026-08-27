import pytest

from broker.deriv_auth import DerivPATOTPTransport


@pytest.mark.asyncio
async def test_options_account_discovery_is_get_only_and_returns_payload():
    calls = []

    async def get(url, headers):
        calls.append((url, headers))
        return 200, {"data": [{"account_id": "DOT90004580", "account_type": "demo"}]}

    transport = DerivPATOTPTransport(http_get=get)
    status, payload = await transport.get_options_accounts(app_id="app", authorization="Bearer fake")
    assert status == 200
    assert payload["data"][0]["account_id"] == "DOT90004580"
    assert calls[0][0].endswith("/trading/v1/options/accounts")
    assert calls[0][1]["Content-Type"] == "application/json"


@pytest.mark.asyncio
async def test_account_discovery_does_not_call_otp():
    transport = DerivPATOTPTransport(http_get=lambda *_: None)
    assert not hasattr(transport, "_otp_attempts")
