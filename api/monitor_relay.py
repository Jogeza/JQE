"""Separate owner-only observation relay. Never imports the broker or API app."""
from collections import deque
from pathlib import Path
import asyncio
import json
import logging
import os
import re
import time
import urllib.error
import urllib.request

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
import jwt

ALLOWED = {
    "/api/v1/journal": {"limit", "symbol"},
    "/api/v1/market/candles": {"symbol", "timeframe", "count"},
    "/api/v1/observation/health": set(),
    **{f"/api/v1/{path}": {"symbol", "timeframe", "count"} for path in (
        "market/summary", "signal", "market/setup", "market/active-analysis",
        "risk", "brokers/terminal-observation")},
    **{f"/api/v1/{path}": set() for path in (
        "system", "execution", "execution/safety", "execution/recovery",
        "execution/paper-runtime", "performance", "brokers/status", "watchlist",
        "monitoring/offline", "notifications/status", "research/paper-diagnostics")},
    "/api/v1/watchlist/cap-usage": {"account_scope"},
}
ROOT = Path(__file__).resolve().parents[1]
QUEUE_TIMEOUT_SECONDS = 1.0


class AccessVerifier:
    def __init__(self, issuer, audience, email, service_client_id=""):
        if not re.fullmatch(r"https://[a-z0-9-]+\.cloudflareaccess\.com", issuer):
            raise ValueError("A Cloudflare Access issuer is required")
        if not audience or not email or "@" not in email:
            raise ValueError("Access audience and owner email are required")
        self.issuer, self.audience, self.email = issuer, audience, email.lower()
        self.service_client_id = service_client_id
        self.keys = jwt.PyJWKClient(issuer + "/cdn-cgi/access/certs", timeout=5)

    def __call__(self, token):
        if not token or len(token) > 16384:
            raise ValueError("Missing token")
        key = self.keys.get_signing_key_from_jwt(token).key
        claims = jwt.decode(token, key, algorithms=["RS256"],
                            issuer=self.issuer, audience=self.audience,
                            options={"require": ["exp", "iat", "iss", "aud", "sub"]})
        if (self.service_client_id and claims.get("common_name") == self.service_client_id
                and claims.get("sub") == ""):
            return "vercel-owner-relay"
        if not claims.get("sub") or str(claims.get("email", "")).lower() != self.email:
            raise ValueError("Unauthorized identity")
        return claims["sub"]


def fetch_local(path, query):
    # Fixed origin, no redirects, no incoming credentials or arbitrary headers.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    url = "http://127.0.0.1:8000" + path + ("?" + query if query else "")
    with urllib.request.build_opener(NoRedirect).open(url, timeout=12) as result:
        content_type = result.headers.get("Content-Type", "")
        if not content_type.startswith("application/json"):
            raise ValueError("Unexpected origin response")
        body = result.read(2_000_001)
        if len(body) > 2_000_000:
            raise ValueError("Origin response too large")
        json.loads(body)
        return body


def create_app(verifier=None, fetcher=fetch_local):
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    if verifier is None:
        verifier = AccessVerifier(os.environ.get("JQE_MONITOR_ISSUER", ""),
                                  os.environ.get("JQE_MONITOR_AUDIENCE", ""),
                                  os.environ.get("JQE_MONITOR_EMAIL", ""),
                                  os.environ.get("JQE_MONITOR_SERVICE_CLIENT_ID", ""))
    # A single authorized owner; one bounded limiter avoids unbounded identity maps.
    requests = deque()
    inflight = asyncio.Semaphore(4)

    @app.middleware("http")
    async def boundary(request: Request, call_next):
        headers = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                   "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY",
                   "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"}
        if request.headers.get("host") not in {"monitor.jokiholdings.com", "127.0.0.1:8766", "testserver"}:
            return JSONResponse({"detail": "Invalid host"}, 400, headers=headers)
        if request.method != "GET":
            return JSONResponse({"detail": "Read-only monitor"}, 405, headers=headers)
        path = request.url.path
        if path not in ALLOWED and path not in {"/", "/monitor.js", "/monitor.css"}:
            return JSONResponse({"detail": "Route unavailable"}, 404, headers=headers)
        if len(request.url.query) > 2048 or any(k not in ALLOWED.get(path, set()) for k in request.query_params):
            return JSONResponse({"detail": "Unsupported query"}, 400, headers=headers)
        now = time.monotonic()
        while requests and requests[0] <= now - 60:
            requests.popleft()
        if len(requests) >= 600:
            return JSONResponse({"detail": "Rate limit reached"}, 429, headers=headers)
        requests.append(now)
        try:
            await asyncio.to_thread(verifier, request.headers.get("Cf-Access-Jwt-Assertion", ""))
        except Exception:
            return JSONResponse({"detail": "Valid owner sign-in required"}, 403, headers=headers)
        # Do not let obsolete requests wait indefinitely beyond the hosted
        # proxy's 20-second timeout. Keep the same four origin slots and quota.
        try:
            await asyncio.wait_for(inflight.acquire(), timeout=QUEUE_TIMEOUT_SECONDS)
        except TimeoutError:
            logging.getLogger(__name__).warning('Monitor origin queue saturated: path=%s', path)
            return JSONResponse({'detail': 'Workstation monitor is busy; retry shortly'}, 503,
                                headers={**headers, 'Retry-After': '2'})
        try:
            response = await call_next(request)
        finally:
            inflight.release()
        response.headers.update(headers)
        return response

    @app.get("/")
    def index():
        return HTMLResponse((ROOT / "monitoring/web/index.html").read_text(encoding="utf-8"))

    @app.get("/monitor.js")
    def script():
        return Response((ROOT / "monitoring/web/monitor.js").read_text(encoding="utf-8"), media_type="application/javascript")

    @app.get("/monitor.css")
    def style():
        return Response((ROOT / "monitoring/web/monitor.css").read_text(encoding="utf-8"), media_type="text/css")

    @app.get("/api/v1/{resource:path}")
    async def observation(resource: str, request: Request):
        try:
            body = await asyncio.to_thread(fetcher, request.url.path, request.url.query)
            return Response(body, media_type="application/json")
        except (OSError, ValueError, urllib.error.URLError):
            return JSONResponse({"detail": "Workstation evidence unavailable"}, 503)
    return app
