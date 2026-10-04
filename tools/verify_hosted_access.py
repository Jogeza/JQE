"""Opt-in real provider contract checks using isolated generated test identities.

Uses server configuration in memory. No emails are sent, no owner accounts or
MT5 state are touched, and no credentials, links or JWTs are saved or printed.
Test identities are retained for audit; their IDs are recorded in the report.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import secrets
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

from audit_hosted_auth import ROOT, config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="Authorize isolated live Auth/access test mutations")
    args = parser.parse_args()
    if not args.run:
        parser.error("Live test identities require --run")
    values = config(ROOT / ".env")
    base = values["SUPABASE_URL"].rstrip("/")
    anon = values["SUPABASE_ANON_KEY"]
    secret = values["SUPABASE_SECRET_KEY"]
    results = []
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    identities = []

    def call(path, *, token=None, admin=False, payload=None, method=None, production=False):
        key = secret if admin else anon
        headers = {"apikey": key, "Authorization": "Bearer " + (token or key), "Content-Type": "application/json", "Prefer": "return=representation"}
        data = None if payload is None else json.dumps(payload).encode()
        try:
            with urlopen(Request(("https://jqe.vercel.app" if production else base) + path, headers=headers, data=data, method=method), timeout=20) as response:
                raw = response.read()
                return response.status, json.loads(raw) if raw else None
        except HTTPError as exc:
            try:
                return exc.code, json.load(exc)
            except ValueError:
                return exc.code, {}
        except (URLError, TimeoutError, OSError):
            return 0, {}

    def check(name, ok, **evidence):
        result = {"check": name, "status": "PASS" if ok else "BLOCKED", **evidence}
        results.append(result)
        print(json.dumps(result), flush=True)

    def rpc(name, token, body=None):
        return call("/rest/v1/rpc/" + name, token=token, payload=body or {})

    def create(label, path):
        email = f"jqe-auth-audit-{run_id.lower()}-{label}-{secrets.token_hex(4)}@example.com"
        password = secrets.token_urlsafe(32)
        status, link = call("/auth/v1/admin/generate_link", admin=True, payload={"type": "signup", "email": email, "password": password, "data": {"onboarding_path": path, "role": "admin", "jqe_auth_audit": run_id}, "redirect_to": "https://jqe.vercel.app/onboarding"})
        check(label + ":generated_signup", status == 200, http_status=status)
        if status != 200:
            raise RuntimeError("Test identity generation blocked")
        uid = link.get("id") or link.get("user", {}).get("id")
        identities.append({"label": label, "id": uid})
        redirect = parse_qs(urlparse(link.get("action_link", "")).query).get("redirect_to", [None])[0]
        check(label + ":signup_redirect", redirect == "https://jqe.vercel.app/onboarding", redirect=redirect)
        status, login = call("/auth/v1/token?grant_type=password", payload={"email": email, "password": password})
        check(label + ":unconfirmed_login_denied", status == 400 and login.get("error_code") == "email_not_confirmed", http_status=status, code=login.get("error_code"))
        status, session = call("/auth/v1/verify", payload={"type": "signup", "token_hash": link.get("hashed_token")})
        check(label + ":provider_confirmation_token", status == 200 and bool(session.get("access_token")), http_status=status, note="Generated token verification; email delivery and browser callback remain separate checks")
        status, login = call("/auth/v1/token?grant_type=password", payload={"email": email, "password": password})
        check(label + ":password_login", status == 200 and bool(login.get("access_token")), http_status=status)
        return uid, email, password, login

    try:
        uid, email, password, session = create("existing", "existing_account")
        token = session["access_token"]
        other_uid, other_email, other_password, other_session = create("referral", "referral")
        other_token = other_session["access_token"]
        status, access = rpc("jqe_access_snapshot", token)
        check("trigger_profile_and_ignore_admin_metadata", status == 200 and access.get("role") == "user" and access.get("onboarding_path") == "existing_account", http_status=status)
        check("trial_requires_explicit_activation", status == 200 and access.get("trial_available") is True and access.get("access_granted") is False)
        status, rows = call("/rest/v1/jqe_profiles?select=id", token=token)
        check("profile_user_isolation", status == 200 and rows == [{"id": uid}], http_status=status)
        for name, payload in (("jqe_review_referral", {"p_id": other_uid, "p_status": "APPROVED"}), ("jqe_admin_set_access", {"p_user_id": uid, "p_status": "ACTIVE", "p_expires_at": None}), ("jqe_admin_referrals", {})):
            status, result = rpc(name, token, payload)
            check("non_admin_denied:" + name, status == 403 and result.get("message") == "ADMIN_REQUIRED", http_status=status, code=result.get("code"))
        status, rows = call("/rest/v1/jqe_profiles?id=eq." + uid, token=token, payload={"role": "admin", "access_override": "ACTIVE"}, method="PATCH")
        check("self_promotion_and_access_mutation_denied", status == 403, http_status=status)
        status, trial = rpc("jqe_activate_existing_trial", token)
        check("activate_trial", status == 200, http_status=status)
        if status == 200:
            started = datetime.fromisoformat(trial["activated_at"])
            expires = datetime.fromisoformat(trial["expires_at"])
            check("trial_exactly_24_hours_UTC", expires - started == timedelta(hours=24) and started.utcoffset() == timedelta(0) and expires.utcoffset() == timedelta(0))
        status, result = rpc("jqe_activate_existing_trial", token)
        check("duplicate_trial_denied", status == 409 and result.get("message") == "TRIAL_ALREADY_USED", http_status=status)
        status, access = rpc("jqe_access_snapshot", token)
        check("trial_feature_contract", status == 200 and access.get("access_granted") is True and set(access.get("feature_access", [])) == {"workspace_read", "research_read", "ai_chat"} and access.get("backend_state") == "UNAVAILABLE")
        status, result = rpc("jqe_consume_feature", token, {"p_feature": None})
        check("null_feature_denied", status == 403 and result.get("message") == "FEATURE_ACCESS_DENIED", http_status=status)
        status, result = call("/api/v1/market/candles", token=token, production=True)
        check("entitled_hosted_MT5_truthful_unavailable", status == 503 and result.get("reason_code") == "LOCAL_BACKEND_ONLY" and result.get("state") == "UNAVAILABLE", http_status=status)
        limit = access.get("ai_daily_limit", 0)
        if isinstance(limit, int) and 0 <= limit <= 20:
            with ThreadPoolExecutor(max_workers=8) as pool:
                responses = list(pool.map(lambda _: rpc("jqe_consume_feature", token, {"p_feature": "ai_chat"}), range(limit + 3)))
            allowed = [row[1].get("used") for row in responses if row[0] == 200 and row[1].get("allowed") is True]
            denied = [row for row in responses if row[0] == 200 and row[1].get("allowed") is False]
            check("atomic_AI_quota_and_exhaustion", sorted(allowed) == list(range(1, limit + 1)) and len(denied) == 3, configured_limit=limit, accepted=len(allowed), denied=len(denied))
        status, rows = call("/rest/v1/jqe_usage_counters?select=user_id,used", token=other_token)
        check("usage_user_isolation", status == 200 and rows == [], http_status=status)
        status, result = rpc("jqe_submit_referral", other_token, {"p_note": "Isolated automated auth audit; not registration evidence."})
        check("referral_submission", status == 200 and result.get("status") == "PENDING", http_status=status)
        status, result = call("/rest/v1/jqe_referral_applications?user_id=eq." + other_uid, admin=True, payload={"status": "APPROVED"}, method="PATCH")
        status, access = rpc("jqe_access_snapshot", other_token)
        check("approved_referral_has_no_entitlement", status == 200 and access.get("referral_status") == "APPROVED" and access.get("access_granted") is False)
        now = datetime.now(timezone.utc)
        status, result = call("/rest/v1/jqe_trial_activations?user_id=eq." + uid, admin=True, payload={"activated_at": (now - timedelta(hours=25)).isoformat(), "expires_at": (now - timedelta(hours=1)).isoformat()}, method="PATCH")
        check("test_only_expiry_fixture", status == 200, http_status=status)
        status, access = rpc("jqe_access_snapshot", token)
        check("expired_trial_denied", status == 200 and access.get("access_status") == "TRIAL_EXPIRED" and access.get("access_granted") is False)
        status, result = rpc("jqe_consume_feature", token, {"p_feature": "ai_chat"})
        check("expired_trial_AI_denied", status == 403 and result.get("message") == "FEATURE_ACCESS_DENIED", http_status=status)
        for path in ("/api/access", "/api/admin/referrals", "/api/v1/market/candles"):
            status, result = call(path, token=token, production=True)
            expected = 200 if path == "/api/access" else 403
            check("production_signed_request:" + path, status == expected, http_status=status)
        status, plans = call("/rest/v1/jqe_plan_catalog?select=price,status", admin=True)
        check("pricing_unset_payments_inactive", status == 200 and all(p.get("price") is None and p.get("status") == "NOT_CONFIGURED" for p in plans), http_status=status)
        for destination in (None, "https://jqe.vercel.app/recover"):
            body = {"type": "recovery", "email": email}
            if destination:
                body["redirect_to"] = destination
            status, link = call("/auth/v1/admin/generate_link", admin=True, payload=body)
            redirect = parse_qs(urlparse(link.get("action_link", "")).query).get("redirect_to", [None])[0]
            check("recovery_redirect" if destination else "default_site_url", status == 200 and redirect == (destination or "https://jqe.vercel.app"), http_status=status, redirect=redirect)
        status, result = call("/auth/v1/logout", token=token, payload={})
        check("provider_logout", status in (200, 204), http_status=status)
        status, result = call("/auth/v1/token?grant_type=refresh_token", payload={"refresh_token": session["refresh_token"]})
        check("logout_revokes_refresh_session", status == 400, http_status=status)
        status, result = call("/api/access", token="expired-or-invalid-test-token", production=True)
        check("production_invalid_session_denied", status == 401 and result.get("reason_code") == "INVALID_SESSION", http_status=status, note="Invalid token; natural JWT expiry is not verified")
    except (KeyError, TypeError, RuntimeError, ValueError):
        check("remaining_checks", False, reason="Provider contract check could not continue; inspect preceding sanitized results")
    finally:
        report = ROOT / "reports" / ("hosted-auth-" + run_id + ".json")
        report.parent.mkdir(exist_ok=True)
        report.write_text(json.dumps({"run_utc": run_id, "test_identities": identities, "checks": results, "email_delivery_verified": False, "browser_callbacks_verified": False}, indent=2), encoding="utf-8")
        print("Report: " + str(report), flush=True)


if __name__ == "__main__":
    main()
