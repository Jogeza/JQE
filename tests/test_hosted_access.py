"""Offline tests for Vercel auth/entitlement handlers; no provider credentials or network."""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

API_ROOT = Path(__file__).resolve().parents[1] / "frontend" / "api"
sys.path.insert(0, str(API_ROOT))

import hosted_assistant  # noqa: E402
import hosted_auth  # noqa: E402
import unavailable  # noqa: E402
from _lib import security  # noqa: E402


class RequestHarness:
    def __init__(self, path: str, *, method: str = "GET", body: object | None = None, authorized: bool = True):
        self.path = path
        self.command = method
        self.headers = {"Authorization": "Bearer test-token"} if authorized else {}
        encoded = b"" if body is None else json.dumps(body).encode()
        self.headers["Content-Length"] = str(len(encoded))
        self.rfile = io.BytesIO(encoded)
        self.wfile = io.BytesIO()
        self.status = None
        self.response_headers = {}
        self.send_response = lambda status, *_args: setattr(self, "status", status)
        self.send_header = lambda key, value: self.response_headers.__setitem__(key, value)
        self.end_headers = lambda: None

    def json(self):
        return json.loads(self.wfile.getvalue())


def dispatch(handler_class, method: str, request: RequestHarness):
    instance = object.__new__(handler_class)
    for name in ("path", "command", "headers", "rfile", "wfile"):
        setattr(instance, name, getattr(request, name))
    instance.status = None
    instance.response_headers = {}
    instance.send_response = lambda status, *_args: setattr(instance, "status", status)
    instance.send_header = lambda key, value: instance.response_headers.__setitem__(key, value)
    instance.end_headers = lambda: None
    instance.json = lambda: json.loads(instance.wfile.getvalue())
    getattr(instance, method)()
    return instance


def test_security_is_fail_closed_without_provider_configuration(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)
    request = dispatch(hosted_auth.handler, "do_GET", RequestHarness("/api/access?operation=access"))
    assert request.status == 503
    assert request.json()["reason_code"] == "AUTH_BACKEND_UNCONFIGURED"


def test_access_route_requires_database_entitlement(monkeypatch):
    expected = {"authenticated": True, "role": "user", "access_status": "TRIAL_ACTIVE", "access_granted": True}
    monkeypatch.setattr(hosted_auth, "authenticate", lambda _headers: ("validated-user-jwt", {"id": "user-1"}))
    monkeypatch.setattr(hosted_auth, "access_for", lambda token: expected if token == "validated-user-jwt" else {})
    request = dispatch(hosted_auth.handler, "do_GET", RequestHarness("/api/hosted_auth?operation=access"))
    assert request.status == 200
    assert request.json() == expected
    assert request.response_headers["Cache-Control"] == "no-store"


def test_admin_mutation_uses_database_role_check(monkeypatch):
    calls = []
    monkeypatch.setattr(hosted_auth, "authenticate", lambda _headers: ("signed-user-jwt", {"id": "user-1"}))
    monkeypatch.setattr(hosted_auth, "rpc", lambda token, name, payload=None: calls.append((token, name, payload)) or (_ for _ in ()).throw(security.SecurityError(403, "ADMIN_REQUIRED", "ADMIN_REQUIRED")))
    request = dispatch(hosted_auth.handler, "do_PATCH", RequestHarness("/api/hosted_auth?operation=admin-referrals", method="PATCH", body={"id": "ref-1", "status": "APPROVED"}))
    assert request.status == 403
    assert calls == [("signed-user-jwt", "jqe_review_referral", {"p_id": "ref-1", "p_status": "APPROVED"})]


def test_paid_trial_cannot_activate_through_legacy_free_route(monkeypatch):
    calls = []
    monkeypatch.setattr(hosted_auth, "authenticate", lambda _headers: ("signed-user-jwt", {"id": "user-1"}))
    monkeypatch.setattr(hosted_auth, "rpc", lambda token, name, payload=None: calls.append((token, name, payload)) or {"status": "PENDING"})
    referral_request = dispatch(hosted_auth.handler, "do_POST", RequestHarness("/api/hosted_auth?operation=referral", method="POST", body={"note": "receipt reference"}))
    trial_request = dispatch(hosted_auth.handler, "do_POST", RequestHarness("/api/hosted_auth?operation=trial-activate", method="POST", body={}))
    assert trial_request.status == 403
    assert trial_request.json()["reason_code"] == "PAID_ACCESS_CHECKOUT_UNAVAILABLE"
    assert calls == [
        ("signed-user-jwt", "jqe_submit_referral", {"p_note": "receipt reference"}),
    ]


def test_order_submission_route_is_not_published(monkeypatch):
    authenticate = Mock(side_effect=AssertionError("order route must not authenticate then submit"))
    monkeypatch.setattr(unavailable, "authenticate", authenticate)
    request = dispatch(unavailable.handler, "do_POST", RequestHarness("/api/hosted_unavailable?resource=execution/cycle", method="POST", body={"confirmed": True}, authorized=False))
    assert request.status == 404
    assert authenticate.call_count == 0
    assert "not available" in request.json()["detail"]


def test_hosted_market_requires_session_then_states_backend_unavailable(monkeypatch):
    monkeypatch.setattr(unavailable, "authenticate", lambda _headers: ("signed-user-jwt", {"id": "user-1"}))
    monkeypatch.setattr(unavailable, "require_feature", lambda _token, feature: {"feature": feature})
    request = dispatch(unavailable.handler, "do_GET", RequestHarness("/api/hosted_unavailable?resource=market/candles"))
    assert request.status == 503
    assert request.json()["reason_code"] == "LOCAL_BACKEND_ONLY"
    assert request.json()["backend_state"] == "UNAVAILABLE"


def test_ai_quota_is_consumed_server_side_before_provider_call(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-only")
    monkeypatch.setattr(hosted_assistant.handler, "_session", lambda _self: ("signed-user-jwt", {"access_granted": True}))
    monkeypatch.setattr(hosted_assistant, "rpc", lambda token, name, payload: {
        "allowed": False, "used": 5, "limit": 5,
    })
    ask = Mock(side_effect=AssertionError("provider must not be called after cap"))
    monkeypatch.setattr(hosted_assistant.handler, "_ask", ask)
    request = dispatch(hosted_assistant.handler, "do_POST", RequestHarness("/api/hosted_assistant?resource=chat", method="POST", body={"message": "hello"}))
    assert request.status == 429
    assert request.json()["reason_code"] == "AI_DAILY_LIMIT_REACHED"
    ask.assert_not_called()


def test_database_defines_unique_24_hour_trial_and_no_referral_auto_grant():
    migration = (Path(__file__).resolve().parents[1] / "supabase" / "migrations" / "20261004000100_jqe_access.sql").read_text(encoding="utf-8")
    assert "user_id uuid primary key references auth.users(id)" in migration
    assert "expires_at = activated_at + interval '24 hours'" in migration
    assert "jqe_activate_existing_trial" in migration
    assert "jqe_review_referral" in migration
    assert "resolved_expiry := case when p_status = 'ACTIVE' then now() + interval '24 hours' else null end" in migration
    assert "'access_granted', allowed" in migration
    assert "price numeric(12, 2)" in migration
