"""Owner-only authenticated Vercel proxy to the read-only Cloudflare relay."""
import json
import logging
import os
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lib.security import SecurityError, authenticate, require_feature, write_json

ROUTES = {
    "journal": {"symbol", "limit"}, "market/candles": {"symbol", "timeframe", "count"},
    **{path: {"symbol", "timeframe", "count"} for path in (
        "market/summary", "signal", "market/setup", "market/active-analysis", "risk",
        "brokers/terminal-observation")},
    **{path: set() for path in ("system", "execution", "execution/safety",
        "execution/recovery", "execution/paper-runtime", "performance", "brokers/status",
        "watchlist", "monitoring/offline", "observation/health", "notifications/status",
        "research/paper-diagnostics")},
    "watchlist/cap-usage": {"account_scope"},
}


def relay_request(resource, query):
    client = os.environ.get("JQE_MONITOR_CF_CLIENT_ID", "")
    secret = os.environ.get("JQE_MONITOR_CF_CLIENT_SECRET", "")
    if not client or not secret:
        raise SecurityError(503, "Live monitoring relay is not configured.", "MONITOR_UNCONFIGURED")
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    request = urllib.request.Request(
        "https://monitor.jokiholdings.com/api/v1/" + resource + ("?" + query if query else ""),
        headers={"Accept": "application/json", "User-Agent": "JQE-Owner-Monitor/1.0", "CF-Access-Client-Id": client,
                 "CF-Access-Client-Secret": secret}, method="GET")
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=20) as response:
            if not response.headers.get("Content-Type", "").startswith("application/json"):
                raise ValueError("Unexpected relay response")
            body = response.read(2_000_001)
            if len(body) > 2_000_000:
                raise ValueError("Relay response exceeds limit")
            return json.loads(body)
    except (OSError, ValueError, urllib.error.URLError) as exc:
        # Diagnose transport failures without recording credentials or response bodies.
        failure_headers = getattr(exc, "headers", {}) or {}
        relay_identity_rejected = False
        if isinstance(exc, urllib.error.HTTPError) and failure_headers.get("Content-Type", "").startswith("application/json"):
            try:
                relay_identity_rejected = json.loads(exc.read(4096)).get("detail") == "Valid owner sign-in required"
            except (ValueError, OSError):
                pass
        logging.getLogger(__name__).warning(
            "Monitor transport failed: %s status=%s json=%s challenged=%s relay_identity_rejected=%s cloudflare=%s vercel=%s",
            type(exc).__name__, getattr(exc, "code", "none"),
            failure_headers.get("Content-Type", "").startswith("application/json"),
            failure_headers.get("cf-mitigated", "") == "challenge", relay_identity_rejected,
            failure_headers.get("Server", "").lower() == "cloudflare", bool(failure_headers.get("x-vercel-id")))
        raise SecurityError(503, "Workstation live evidence is unavailable.", "MONITOR_UNAVAILABLE") from None


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        params = parse_qsl(urlparse(self.path).query, keep_blank_values=True)
        resources = [v for k, v in params if k == "resource"]
        resource = resources[0] if len(resources) == 1 else ""
        if resource not in ROUTES:
            return write_json(self, 404, {"detail": "Hosted monitoring route unavailable."})
        query = [(k, v) for k, v in params if k != "resource"]
        if len(self.path) > 4096 or any(k not in ROUTES[resource] for k, _ in query):
            return write_json(self, 400, {"detail": "Unsupported monitoring query."})
        try:
            token, user = authenticate(self.headers)
            owner = os.environ.get("JQE_MONITOR_OWNER_EMAIL", "").lower()
            if not owner or str(user.get("email", "")).lower() != owner:
                raise SecurityError(403, "Workstation monitoring is restricted to its owner.", "MONITOR_OWNER_ONLY")
            require_feature(token, "research_read" if resource.startswith("research/") else "workspace_read")
            payload = relay_request(resource, urlencode(query))
        except SecurityError as exc:
            return write_json(self, exc.status, {"detail": exc.detail, "reason_code": exc.reason_code, "state": "UNAVAILABLE"})
        return write_json(self, 200, payload)

    def do_POST(self):
        write_json(self, 405, {"detail": "Hosted monitoring is read-only."})
    do_PATCH = do_POST
    do_PUT = do_POST
    do_DELETE = do_POST

    def log_message(self, *args):
        pass
