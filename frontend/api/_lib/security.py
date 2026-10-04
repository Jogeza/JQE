"""Shared fail-closed Supabase session and entitlement checks for Vercel handlers."""
import json
import os
import urllib.error
import urllib.request


class SecurityError(Exception):
    def __init__(self, status, detail, reason_code):
        super().__init__(detail)
        self.status = status
        self.detail = detail
        self.reason_code = reason_code


def _config():
    url = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
    anon_key = os.environ.get("SUPABASE_ANON_KEY") or ""
    if not url or not anon_key:
        raise SecurityError(503, "Hosted authentication is not configured.", "AUTH_BACKEND_UNCONFIGURED")
    return url, anon_key


def bearer_token(headers):
    value = headers.get("Authorization", "")
    scheme, _, token = value.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise SecurityError(401, "A valid sign-in session is required.", "AUTHENTICATION_REQUIRED")
    return token.strip()


def authenticate(headers):
    url, anon_key = _config()
    token = bearer_token(headers)
    request = urllib.request.Request(
        f"{url}/auth/v1/user",
        headers={"apikey": anon_key, "Authorization": f"Bearer {token}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            user = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise SecurityError(401, "Sign-in session is invalid or expired.", "INVALID_SESSION") from exc
        raise SecurityError(503, "Authentication provider is unavailable.", "AUTH_PROVIDER_UNAVAILABLE") from exc
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        raise SecurityError(503, "Authentication provider is unavailable.", "AUTH_PROVIDER_UNAVAILABLE") from exc
    if not isinstance(user, dict) or not user.get("id") or not user.get("email"):
        raise SecurityError(401, "Sign-in session is invalid.", "INVALID_SESSION")
    return token, user


def rpc(token, function_name, payload=None):
    url, anon_key = _config()
    request = urllib.request.Request(
        f"{url}/rest/v1/rpc/{function_name}",
        data=json.dumps(payload or {}).encode("utf-8"),
        headers={
            "apikey": anon_key,
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise SecurityError(403, "The requested access is not permitted.", "ACCESS_DENIED") from exc
        raise SecurityError(503, "Access service is unavailable.", "ACCESS_SERVICE_UNAVAILABLE") from exc
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        raise SecurityError(503, "Access service is unavailable.", "ACCESS_SERVICE_UNAVAILABLE") from exc


def access_for(token):
    result = rpc(token, "jqe_access_snapshot")
    if not isinstance(result, dict) or result.get("authenticated") is not True:
        raise SecurityError(503, "Access state is unavailable.", "ACCESS_STATE_INVALID")
    return result


def require_feature(token, feature):
    access = access_for(token)
    features = access.get("feature_access")
    if access.get("access_granted") is not True or not isinstance(features, list) or feature not in features:
        raise SecurityError(403, "This feature is not included in current access.", "FEATURE_ACCESS_DENIED")
    return access


def write_json(handler, status, payload):
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)
