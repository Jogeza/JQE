"""Opt-in public signup/email checks; generated test password stays in memory.

The inbox owner must confirm the email. No tokens or credentials are printed.
"""
import argparse
import json
import secrets
import time
from urllib.parse import quote

from audit_hosted_auth import ROOT, config, request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True, help="Explicitly authorized test inbox")
    parser.add_argument("--wait-seconds", type=int, default=600)
    args = parser.parse_args()
    values = config(ROOT / ".env")
    base = values["SUPABASE_URL"].rstrip("/")
    key = values["SUPABASE_ANON_KEY"]
    secret = values["SUPABASE_SECRET_KEY"]
    headers = {"apikey": key, "Authorization": "Bearer " + key, "Content-Type": "application/json"}
    admin_headers = {"apikey": secret, "Authorization": "Bearer " + secret}
    password = secrets.token_urlsafe(32)
    status, signup = request(base + "/auth/v1/signup?redirect_to=" + quote("https://jqe.vercel.app/onboarding", safe=""), headers, {"email": args.email, "password": password, "data": {"onboarding_path": "existing_account"}})
    print(json.dumps({"check": "public_signup_email_request", "http_status": status, "code": signup.get("error_code"), "session_issued": bool(signup.get("access_token"))}), flush=True)
    if status != 200:
        return
    uid = signup.get("id") or signup.get("user", {}).get("id")
    if not uid:
        print("BLOCKED: provider did not return an identity", flush=True)
        return
    print("WAITING: inbox owner must open the signup confirmation email.", flush=True)
    confirmed = False
    deadline = time.monotonic() + args.wait_seconds
    while time.monotonic() < deadline:
        status, user = request(base + "/auth/v1/admin/users/" + uid, admin_headers)
        if status == 200 and user.get("email_confirmed_at"):
            confirmed = True
            print("PASS: real inbox confirmation recorded by Supabase.", flush=True)
            break
        time.sleep(5)
    if not confirmed:
        print("BLOCKED: email confirmation remains pending.", flush=True)
        return
    status, session = request(base + "/auth/v1/token?grant_type=password", headers, {"email": args.email, "password": password})
    print(json.dumps({"check": "real_confirmed_password_login", "http_status": status, "session_issued": bool(session.get("access_token"))}), flush=True)
    status, recovery = request(base + "/auth/v1/recover?redirect_to=" + quote("https://jqe.vercel.app/recover", safe=""), headers, {"email": args.email})
    print(json.dumps({"check": "real_recovery_email_request", "http_status": status, "code": recovery.get("error_code")}), flush=True)
    print("WAITING: inbox owner must open the recovery email and set their own JQE password. Generated signup password is not retained.", flush=True)


if __name__ == "__main__":
    main()
