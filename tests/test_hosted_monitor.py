"""Owner authorization precedes relay credential use; tests are fully offline."""
import sys
import json
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "frontend/api"))
import hosted_monitor
from tests.test_hosted_access import RequestHarness, dispatch
from _lib.security import SecurityError


def test_vercel_routes_are_exact_and_unsupported_paths_fail_closed():
    config = json.loads((Path(__file__).resolve().parents[1] / "frontend/vercel.json").read_text())
    rules = config["rewrites"]
    for resource in hosted_monitor.ROUTES:
        assert {"source": "/api/v1/" + resource,
                "destination": "/api/hosted_monitor?resource=" + resource} in rules
    fallback = next(rule for rule in rules if rule["source"] == "/api/v1/:path*")
    assert fallback["destination"] == "/api/hosted_unavailable"
    assert rules.index(fallback) > max(i for i, rule in enumerate(rules)
                                    if rule["destination"].startswith("/api/hosted_monitor?"))


def test_no_authentication_or_mutation_can_reach_relay(monkeypatch):
    relay = Mock(side_effect=AssertionError("must not reach relay"))
    monkeypatch.setattr(hosted_monitor, "relay_request", relay)
    monkeypatch.setattr(hosted_monitor, "authenticate", Mock(side_effect=SecurityError(401, "Sign in required", "AUTH_REQUIRED")))
    for method in ("do_POST", "do_PATCH", "do_PUT", "do_DELETE"):
        assert dispatch(hosted_monitor.handler, method, RequestHarness("/?resource=journal")).status == 405
    assert dispatch(hosted_monitor.handler, "do_GET", RequestHarness("/?resource=journal")).status == 401
    for path in ("execution/cycle", "orders", "brokers/select", "../journal", "research/history/acquire"):
        assert dispatch(hosted_monitor.handler, "do_GET", RequestHarness("/?resource=" + path)).status == 404
    relay.assert_not_called()


def test_owner_and_entitlement_are_both_required(monkeypatch):
    relay = Mock(return_value={"state": "OBSERVED"})
    entitlement = Mock(return_value={})
    monkeypatch.setattr(hosted_monitor, "relay_request", relay)
    monkeypatch.setattr(hosted_monitor, "require_feature", entitlement)
    monkeypatch.setattr(hosted_monitor, "authenticate", lambda _: ("user-token", {"email": "owner@example.com"}))
    monkeypatch.setenv("JQE_MONITOR_OWNER_EMAIL", "other@example.com")
    assert dispatch(hosted_monitor.handler, "do_GET", RequestHarness("/?resource=journal")).status == 403
    entitlement.assert_not_called()
    relay.assert_not_called()
    monkeypatch.setenv("JQE_MONITOR_OWNER_EMAIL", "owner@example.com")
    entitlement.side_effect = SecurityError(403, "No entitlement", "DENIED")
    assert dispatch(hosted_monitor.handler, "do_GET", RequestHarness("/?resource=journal")).status == 403
    relay.assert_not_called()
    entitlement.side_effect = None
    response = dispatch(hosted_monitor.handler, "do_GET", RequestHarness("/?resource=journal&limit=10"))
    assert response.status == 200
    assert response.response_headers["Cache-Control"] == "no-store"
    relay.assert_called_once_with("journal", "limit=10")
    entitlement.assert_called_with("user-token", "workspace_read")


def test_query_allowlist_and_missing_credentials(monkeypatch):
    assert dispatch(hosted_monitor.handler, "do_GET", RequestHarness("/?resource=journal&url=https://evil.example")).status == 400
    assert dispatch(hosted_monitor.handler, "do_GET", RequestHarness("/?resource=journal&resource=system")).status == 404
    monkeypatch.delenv("JQE_MONITOR_CF_CLIENT_ID", raising=False)
    monkeypatch.delenv("JQE_MONITOR_CF_CLIENT_SECRET", raising=False)
    try:
        hosted_monitor.relay_request("journal", "")
    except SecurityError as exc:
        assert exc.reason_code == "MONITOR_UNCONFIGURED"
    else:
        raise AssertionError("Missing credentials must reject")
