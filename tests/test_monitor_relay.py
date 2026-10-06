import time
import asyncio
import threading
from unittest.mock import Mock

from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
import jwt
import pytest

from api.monitor_relay import AccessVerifier, create_app


def test_saturated_origin_queue_rejects_promptly_without_forwarding_extra_work(monkeypatch):
    import httpx
    import api.monitor_relay as relay
    monkeypatch.setattr(relay, 'QUEUE_TIMEOUT_SECONDS', 0.05)
    release = threading.Event()
    calls = []
    def fetch(path, query):
        calls.append(path)
        assert release.wait(3)
        return b'{"state":"OBSERVED"}'
    async def run():
        transport = httpx.ASGITransport(app=create_app(lambda _: 'owner', fetch))
        async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
            tasks = [asyncio.create_task(client.get('/api/v1/observation/health')) for _ in range(4)]
            try:
                for _ in range(100):
                    if len(calls) == 4:
                        break
                    await asyncio.sleep(0.005)
                assert len(calls) == 4
                busy = await client.get('/api/v1/observation/health')
                assert busy.status_code == 503
                assert busy.headers['retry-after'] == '2'
                assert busy.headers['cache-control'] == 'no-store'
                assert len(calls) == 4
            finally:
                release.set()
                replies = await asyncio.gather(*tasks)
            assert all(reply.status_code == 200 for reply in replies)
            assert (await client.get('/api/v1/observation/health')).status_code == 200
    asyncio.run(run())


def test_missing_configuration_fails_closed(monkeypatch):
    for key in ("JQE_MONITOR_ISSUER", "JQE_MONITOR_AUDIENCE", "JQE_MONITOR_EMAIL"):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(ValueError):
        create_app()


def test_authentication_and_routes_never_forward_mutations():
    fetch = Mock(return_value=b'{"state":"OBSERVED","items":[]}')
    def verify(token):
        if token != "valid":
            raise ValueError()
        return "owner"
    client = TestClient(create_app(verify, fetch))
    assert client.get("/api/v1/journal").status_code == 403
    assert client.get("/api/v1/journal", headers={"Cf-Access-Authenticated-User-Email": "owner@example.com"}).status_code == 403
    headers = {"Cf-Access-Jwt-Assertion": "valid"}
    assert client.post("/api/v1/journal", headers=headers).status_code == 405
    for path in ("/api/v1/execution/cycle", "/docs", "/api/v1/brokers/select", "/api/v1/journal?url=http://example.com"):
        assert client.get(path, headers=headers).status_code in (400, 404)
    fetch.assert_not_called()
    response = client.get("/api/v1/journal?limit=5", headers=headers)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    fetch.assert_called_once_with("/api/v1/journal", "limit=5")


def test_rate_limit_and_origin_errors():
    fetch = Mock(side_effect=OSError())
    client = TestClient(create_app(lambda _: "owner", fetch))
    assert client.get("/api/v1/journal").status_code == 503
    for _ in range(599):
        client.get("/api/v1/journal")
    assert client.get("/api/v1/journal").status_code == 429


@pytest.mark.parametrize("change", [{"aud": "other"}, {"iss": "https://evil.example"}, {"exp": 1}, {"email": "other@example.com"}, {"sub": None}])
def test_signed_wrong_identity_or_claims_rejected(change):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    verifier = AccessVerifier("https://test-team.cloudflareaccess.com", "monitor", "owner@example.com")
    verifier.keys = Mock()
    verifier.keys.get_signing_key_from_jwt.return_value.key = key.public_key()
    claims = {"iss": verifier.issuer, "aud": "monitor", "email": "owner@example.com", "sub": "owner", "iat": int(time.time()), "exp": int(time.time()) + 60}
    assert verifier(jwt.encode(claims, key, algorithm="RS256")) == "owner"
    claims.update(change)
    with pytest.raises((ValueError, jwt.PyJWTError)):
        verifier(jwt.encode(claims, key, algorithm="RS256"))


def test_invalid_signature_rejected():
    verifier = AccessVerifier("https://test-team.cloudflareaccess.com", "monitor", "owner@example.com")
    verifier.keys = Mock()
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    verifier.keys.get_signing_key_from_jwt.return_value.key = key.public_key()
    token = jwt.encode({"iss": verifier.issuer, "aud": "monitor", "email": "owner@example.com", "sub": "owner", "iat": int(time.time()), "exp": int(time.time()) + 60}, "bad" * 16, algorithm="HS256")
    with pytest.raises(jwt.PyJWTError):
        verifier(token)


def test_service_identity_requires_exact_signed_client_and_empty_subject():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    verifier = AccessVerifier("https://test-team.cloudflareaccess.com", "monitor", "owner@example.com", "vercel-client")
    verifier.keys = Mock()
    verifier.keys.get_signing_key_from_jwt.return_value.key = key.public_key()
    claims = {"iss": verifier.issuer, "aud": "monitor", "sub": "", "common_name": "vercel-client", "iat": int(time.time()), "exp": int(time.time()) + 60}
    assert verifier(jwt.encode(claims, key, algorithm="RS256")) == "vercel-owner-relay"
    for change in ({"common_name": "other"}, {"sub": "unexpected"}):
        with pytest.raises(ValueError):
            verifier(jwt.encode({**claims, **change}, key, algorithm="RS256"))
