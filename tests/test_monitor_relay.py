import time
import asyncio
import logging
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
            tasks = [asyncio.create_task(client.get(f'/api/v1/market/candles?symbol=S{index}')) for index in range(2)]
            tasks.append(asyncio.create_task(client.get('/api/v1/market/active-analysis?symbol=S2')))
            tasks.append(asyncio.create_task(client.get('/api/v1/observation/health')))
            try:
                for _ in range(100):
                    if len(calls) == 4:
                        break
                    await asyncio.sleep(0.005)
                assert len(calls) == 4
                busy = await client.get('/api/v1/market/candles?symbol=extra')
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


def test_identical_concurrent_reads_share_work_but_never_cache_or_skip_auth():
    import httpx
    release = threading.Event()
    calls = []
    def fetch(path, query):
        calls.append((path, query))
        assert release.wait(3)
        return b'{"state":"OBSERVED"}'
    def verify(token):
        if token != 'valid':
            raise ValueError()
        return 'owner'
    async def run():
        transport = httpx.ASGITransport(app=create_app(verify, fetch))
        async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
            headers = {'Cf-Access-Jwt-Assertion': 'valid'}
            tasks = [asyncio.create_task(client.get('/api/v1/observation/health', headers=headers)) for _ in range(8)]
            try:
                for _ in range(100):
                    if calls:
                        break
                    await asyncio.sleep(0.005)
                await asyncio.sleep(0.05)
                assert len(calls) == 1
                assert (await client.get('/api/v1/observation/health')).status_code == 403
                tasks[0].cancel()
                await asyncio.gather(tasks[0], return_exceptions=True)
            finally:
                release.set()
            replies = await asyncio.gather(*tasks[1:])
            assert all(reply.status_code == 200 and reply.headers['cache-control'] == 'no-store' for reply in replies)
            assert len(calls) == 1
            assert (await client.get('/api/v1/observation/health', headers=headers)).status_code == 200
            assert len(calls) == 2
    asyncio.run(run())


def test_market_contention_preserves_one_of_four_origin_slots_for_health():
    import httpx
    release = threading.Event()
    calls = []
    def fetch(path, query):
        calls.append(path)
        if path != '/api/v1/observation/health':
            assert release.wait(3)
        return b'{"state":"OBSERVED"}'
    async def run():
        transport = httpx.ASGITransport(app=create_app(lambda _: 'owner', fetch))
        async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
            tasks = [asyncio.create_task(client.get(f'/api/v1/market/candles?symbol=S{index}')) for index in range(2)]
            tasks.append(asyncio.create_task(client.get('/api/v1/market/active-analysis?symbol=S2')))
            try:
                for _ in range(100):
                    if len(calls) == 3:
                        break
                    await asyncio.sleep(0.005)
                assert len(calls) == 3
                assert (await client.get('/api/v1/observation/health')).status_code == 200
                assert len(calls) == 4
            finally:
                release.set()
                await asyncio.gather(*tasks)
    asyncio.run(run())


def test_background_contention_cannot_consume_the_chart_slot():
    import httpx
    release = threading.Event()
    calls = []
    def fetch(path, query):
        calls.append(path)
        if path != '/api/v1/market/active-analysis':
            assert release.wait(3)
        return b'{"state":"OBSERVED"}'
    async def run():
        transport = httpx.ASGITransport(app=create_app(lambda _: 'owner', fetch))
        async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
            tasks = [asyncio.create_task(client.get(f'/api/v1/market/candles?symbol=S{index}')) for index in range(2)]
            try:
                for _ in range(100):
                    if len(calls) == 2:
                        break
                    await asyncio.sleep(0.005)
                assert len(calls) == 2
                assert (await client.get('/api/v1/market/active-analysis?timeframe=M1')).status_code == 200
                assert len(calls) == 3
            finally:
                release.set()
                await asyncio.gather(*tasks)
    asyncio.run(run())


def test_missing_configuration_fails_closed(monkeypatch):
    for key in ("JQE_MONITOR_ISSUER", "JQE_MONITOR_AUDIENCE", "JQE_MONITOR_EMAIL"):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(ValueError):
        create_app()


def test_coalescing_keeps_timeframes_separate_and_normalizes_query_order():
    import httpx
    release = threading.Event()
    calls = []
    def fetch(path, query):
        calls.append(query)
        assert release.wait(3)
        return b'{"state":"OBSERVED"}'
    async def run():
        transport = httpx.ASGITransport(app=create_app(lambda _: 'owner', fetch))
        async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
            urls = ['/api/v1/market/candles?symbol=FX+Vol+20&timeframe=M1',
                    '/api/v1/market/candles?timeframe=M1&symbol=FX%20Vol%2020',
                    '/api/v1/market/candles?symbol=FX+Vol+20&timeframe=M5']
            tasks = [asyncio.create_task(client.get(url)) for url in urls]
            try:
                for _ in range(100):
                    if len(calls) == 2:
                        break
                    await asyncio.sleep(0.005)
                await asyncio.sleep(0.05)
                assert sorted(calls) == ['symbol=FX+Vol+20&timeframe=M1', 'symbol=FX+Vol+20&timeframe=M5']
            finally:
                release.set()
            assert all(reply.status_code == 200 for reply in await asyncio.gather(*tasks))
    asyncio.run(run())


def test_failed_shared_work_is_evicted_and_can_recover():
    fetch = Mock(side_effect=[OSError(), b'{"state":"OBSERVED"}'])
    client = TestClient(create_app(lambda _: 'owner', fetch))
    assert client.get('/api/v1/observation/health').status_code == 503
    assert client.get('/api/v1/observation/health').status_code == 200
    assert fetch.call_count == 2


def test_timings_and_queue_waits_are_logged_for_every_observed_route(caplog):
    fetch = Mock(return_value=b'{"state":"OBSERVED"}')
    client = TestClient(create_app(lambda _: 'owner', fetch))
    with caplog.at_level(logging.INFO, logger='api.monitor_relay'):
        assert client.get('/api/v1/observation/health').status_code == 200
    lines = [record.getMessage() for record in caplog.records if record.name == 'api.monitor_relay']
    origin = [line for line in lines if line.startswith('origin fetch path=/api/v1/observation/health')]
    assert origin and 'queue_ms=' in origin[0] and 'fetch_ms=' in origin[0]
    assert any(line.startswith('request path=/api/v1/observation/health status=200 shared=False')
               and 'total_ms=' in line for line in lines)


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
