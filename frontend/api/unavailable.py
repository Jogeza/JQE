"""Fail-closed stub for backend routes that only exist on the local deployment.

The hosted frontend has no MT5 terminal, supervisor, or state stores, so every
non-assistant /api/v1 route reports UNAVAILABLE instead of pretending to be live.
"""
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _lib.security import SecurityError, authenticate, require_feature, write_json

REASON = "LOCAL_BACKEND_ONLY"


class handler(BaseHTTPRequestHandler):
    def _resource(self):
        return parse_qs(urlparse(self.path).query).get("resource", [""])[0].strip("/")

    def _unavailable(self):
        resource = self._resource()
        if resource.startswith(("execution/cycle", "execution/watchlist-cycles", "orders", "order")):
            return write_json(self, 404, {"detail": "Hosted order submission is not available."})
        try:
            token, _user = authenticate(self.headers)
            feature = "research_read" if resource.startswith("research/") else "workspace_read"
            require_feature(token, feature)
        except SecurityError as exc:
            return write_json(self, exc.status, {"detail": exc.detail, "reason_code": exc.reason_code, "state": "UNAVAILABLE"})
        write_json(self, 503, {
            "detail": "This JQE evidence source requires the local workstation backend.",
            "reason_code": REASON,
            "state": "UNAVAILABLE",
            "backend_state": "UNAVAILABLE",
        })

    def do_GET(self):
        self._unavailable()

    def do_POST(self):
        self._unavailable()

    def do_PATCH(self):
        self._unavailable()

    def do_PUT(self):
        self._unavailable()

    def do_DELETE(self):
        write_json(self, 405, {"detail": "Method not allowed."})

    def log_message(self, *args):
        pass
