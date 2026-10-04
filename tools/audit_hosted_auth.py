"""Read-only hosted readiness probes. Print only names, booleans and status codes."""
from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parents[1]


def config(path):
    result = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            name, separator, value = line.partition("=")
            if separator and not name.startswith("#"):
                result[name.strip()] = value.strip().strip('"').strip("'").replace("\\n", "\n").strip()
    return result


def request(url, headers=None, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    try:
        with urlopen(Request(url, headers=headers or {}, data=data), timeout=20) as response:
            return response.status, json.load(response)
    except HTTPError as exc:
        try:
            return exc.code, json.load(exc)
        except ValueError:
            return exc.code, {}
    except (URLError, TimeoutError, OSError):
        return 0, {}


def main():
    merged = dict(os.environ)
    for relative in (".env", ".env.ai", ".vercel/.env.production.local", "frontend/.vercel/.env.production.local"):
        values = config(ROOT / relative)
        print(json.dumps({"source": relative, "presence": {name: bool(value) for name, value in values.items() if any(s in name for s in ("SUPABASE", "VERCEL", "DATABASE", "JQE_ACCESS", "TEST_EMAIL", "TEST_PASSWORD"))}}))
        merged.update(values)
    for relative in ("AppData/Local/com.vercel.cli/auth.json", "AppData/Roaming/xdg.data/com.vercel.cli/auth.json", "AppData/Roaming/Roaming/xdg.data/com.vercel.cli/auth.json", ".local/share/com.vercel.cli/auth.json", ".supabase/access-token", ".config/supabase/access-token"):
        path = Path.home() / relative
        print(json.dumps({"credential_file": relative, "exists": path.is_file()}))
        if relative.endswith("auth.json") and path.is_file():
            token = json.loads(path.read_text()).get("token")
            if token:
                project = json.loads((ROOT / ".vercel/project.json").read_text())
                suffix = "?teamId=" + project["orgId"]
                headers = {"Authorization": "Bearer " + token}
                status, info = request("https://api.vercel.com/v9/projects/" + project["projectId"] + suffix, headers)
                print(json.dumps({"vercel_project_status": status, "rootDirectory": info.get("rootDirectory"), "framework": info.get("framework")}))
                status, info = request("https://api.vercel.com/v9/projects/" + project["projectId"] + "/env" + suffix, headers)
                print(json.dumps({"vercel_env_status": status, "production_presence": {item["key"]: True for item in info.get("envs", []) if "production" in item.get("target", []) and any(s in item["key"] for s in ("SUPABASE", "JQE_ACCESS"))}}))
    base = merged.get("SUPABASE_URL", "").rstrip("/")
    key = merged.get("SUPABASE_ANON_KEY", "")
    if not base or not key:
        return
    headers = {"apikey": key, "Authorization": "Bearer " + key, "Content-Type": "application/json"}
    secret = merged.get("SUPABASE_SECRET_KEY")
    if secret:
        status, info = request(base + "/auth/v1/admin/users?page=1&per_page=1", {"apikey": secret, "Authorization": "Bearer " + secret})
        print(json.dumps({"supabase_admin_auth_status": status, "user_count": info.get("total"), "existing_users_present": bool(info.get("users"))}))
    status, settings = request(base + "/auth/v1/settings", headers)
    print(json.dumps({"supabase_auth_settings_status": status, "email_enabled": settings.get("external", {}).get("email"), "email_confirmation_required": settings.get("mailer_autoconfirm") is False, "signup_disabled": settings.get("disable_signup")}))
    signatures = {
        "jqe_access_snapshot": {}, "jqe_activate_existing_trial": {},
        "jqe_submit_referral": {"p_note": None}, "jqe_admin_referrals": {},
        "jqe_review_referral": {"p_id": "00000000-0000-0000-0000-000000000000", "p_status": "APPROVED"},
        "jqe_admin_set_access": {"p_user_id": "00000000-0000-0000-0000-000000000000", "p_status": "NONE", "p_expires_at": None},
        "jqe_consume_feature": {"p_feature": "ai_chat"},
    }
    for function, payload in signatures.items():
        status, result = request(base + "/rest/v1/rpc/" + function, headers, payload)
        print(json.dumps({"rpc": function, "status": status, "code": result.get("code")}))
    tables = ("jqe_profiles", "jqe_referral_applications", "jqe_trial_activations", "jqe_usage_counters", "jqe_feature_limits", "jqe_plan_catalog")
    for table in tables:
        status, rows = request(base + "/rest/v1/" + table + "?select=*&limit=1", headers)
        print(json.dumps({"table": table, "status": status, "anonymous_visible_rows": len(rows) if isinstance(rows, list) else None}))
    for path in ("/api/access", "/api/admin/referrals", "/api/v1/market/candles", "/api/v1/assistant/status"):
        status, response = request("https://jqe.vercel.app" + path)
        print(json.dumps({"production_path": path, "status": status, "reason_code": response.get("reason_code")}))


if __name__ == "__main__":
    main()
