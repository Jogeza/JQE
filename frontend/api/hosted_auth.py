"""Authenticated Vercel handlers for JQE entitlements and onboarding."""
import json
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _lib.security import SecurityError, access_for, authenticate, rpc, write_json


class handler(BaseHTTPRequestHandler):
    def _operation(self):
        return parse_qs(urlparse(self.path).query).get("operation", [""])[0]

    def _body(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length > 8192:
            raise SecurityError(413, "Request body is too large.", "REQUEST_TOO_LARGE")
        try:
            value = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, UnicodeDecodeError) as exc:
            raise SecurityError(400, "Invalid JSON request.", "INVALID_REQUEST") from exc
        if not isinstance(value, dict):
            raise SecurityError(400, "Expected a JSON object.", "INVALID_REQUEST")
        return value

    def _run(self, action):
        try:
            token, user = authenticate(self.headers)
            result = action(token, user)
            write_json(self, 200, result)
        except SecurityError as exc:
            write_json(self, exc.status, {"detail": exc.detail, "reason_code": exc.reason_code})
        except Exception:
            write_json(self, 503, {"detail": "Hosted access service is unavailable.", "reason_code": "ACCESS_SERVICE_UNAVAILABLE"})

    def do_GET(self):
        operation = self._operation()
        if operation == "access":
            return self._run(lambda token, _user: access_for(token))
        if operation == "admin-referrals":
            return self._run(lambda token, _user: rpc(token, "jqe_admin_referrals"))
        write_json(self, 404, {"detail": "Not found."})

    def do_POST(self):
        operation = self._operation()
        try:
            payload = self._body()
        except SecurityError as exc:
            return write_json(self, exc.status, {"detail": exc.detail, "reason_code": exc.reason_code})
        if operation == "referral":
            return self._run(lambda token, _user: rpc(token, "jqe_submit_referral", {"p_note": str(payload.get("note", ""))[:500]}))
        if operation == "trial-activate":
            return self._run(lambda token, _user: rpc(token, "jqe_activate_existing_trial"))
        write_json(self, 404, {"detail": "Not found."})

    def do_PATCH(self):
        operation = self._operation()
        try:
            payload = self._body()
        except SecurityError as exc:
            return write_json(self, exc.status, {"detail": exc.detail, "reason_code": exc.reason_code})
        if operation == "admin-referrals":
            return self._run(lambda token, _user: rpc(token, "jqe_review_referral", {
                "p_id": str(payload.get("id", "")),
                "p_status": str(payload.get("status", "")),
            }))
        if operation == "admin-access":
            return self._run(lambda token, _user: rpc(token, "jqe_admin_set_access", {
                "p_user_id": str(payload.get("user_id", "")),
                "p_status": str(payload.get("status", "")),
                "p_expires_at": payload.get("expires_at"),
            }))
        write_json(self, 404, {"detail": "Not found."})

    def do_DELETE(self):
        write_json(self, 405, {"detail": "Method not allowed."})

    def log_message(self, *_args):
        pass
