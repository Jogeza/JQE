"""Fail-closed stub for backend routes that only exist on the local deployment.

The hosted frontend has no MT5 terminal, supervisor, or state stores, so every
non-assistant /api/v1 route reports UNAVAILABLE instead of pretending to be live.
"""
import json
import os
from http.server import BaseHTTPRequestHandler

REASON = "LOCAL_BACKEND_ONLY"


class handler(BaseHTTPRequestHandler):
    def _send(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._send(503, {"detail": "This evidence source is only available on the local deployment.", "reason_code": REASON, "state": "UNAVAILABLE"})

    def do_POST(self):
        self._send(503, {"detail": "This operation is only available on the local deployment.", "reason_code": REASON, "state": "UNAVAILABLE"})

    def log_message(self, *args):
        pass
