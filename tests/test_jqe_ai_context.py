from datetime import datetime, timezone

import pytest

from jqe_ai.context import SOURCE_NAMES, build_context
from jqe_ai.models import ContextItem, GlossaryBundle


def make_items(data=None):
    return [ContextItem(
        name=name, source=name, stale=name == "risk", available=name != "watchlist",
        data=data or {},
    ) for name in SOURCE_NAMES]


def test_bundle_has_exactly_seven_ordered_sources_and_deterministic_freshness():
    bundle = build_context(
        reader=lambda: (make_items(), GlossaryBundle(version="v1", items=[])),
        built_at=datetime(2026, 9, 21, tzinfo=timezone.utc).isoformat(), maximum_bytes=32768,
    )
    assert [item.name for item in bundle.items] == list(SOURCE_NAMES)
    assert bundle.stale_sources == ["risk"]
    assert bundle.unavailable_sources == ["watchlist"]
    assert bundle.overall_freshness == "MIXED"


@pytest.mark.parametrize("key", ["password", "api_token", "credential", "account_id", "session_id", "filesystem_path"])
def test_privacy_guard_rejects_sensitive_fields(key):
    with pytest.raises(ValueError, match="Sensitive field"):
        build_context(
            reader=lambda: (make_items({key: "must-not-leave"}), GlossaryBundle(version="v1", items=[])),
            built_at="2026-09-21T00:00:00+00:00", maximum_bytes=32768,
        )


def test_context_size_is_measured_after_deterministic_serialization():
    with pytest.raises(ValueError, match="size limit"):
        build_context(
            reader=lambda: (make_items({"payload": "x" * 5000}), GlossaryBundle(version="v1", items=[])),
            built_at="2026-09-21T00:00:00+00:00", maximum_bytes=1024,
        )
