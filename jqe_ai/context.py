"""Build and validate the model-visible Workspace context."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from jqe_ai.models import ContextItem, GlossaryBundle, WorkspaceContextBundle

SOURCE_NAMES = (
    "broker_status", "execution_safety", "risk", "offline_monitoring",
    "observation_health", "watchlist", "watchlist_cap_usage",
)
_SENSITIVE_KEYS = ("password", "token", "secret", "credential", "api_key", "account_id", "session_id", "path")


def _assert_private(value: Any, path: str = "context") -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            lowered = str(key).lower()
            if any(fragment in lowered for fragment in _SENSITIVE_KEYS):
                raise ValueError(f"Sensitive field rejected at {path}")
            _assert_private(nested, f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _assert_private(nested, f"{path}[{index}]")


def build_context(
    *,
    reader: Callable[[], tuple[list[ContextItem], GlossaryBundle]],
    built_at: str,
    maximum_bytes: int,
) -> WorkspaceContextBundle:
    items, glossary = reader()
    if [item.name for item in items] != list(SOURCE_NAMES):
        raise ValueError("Workspace context must contain exactly the seven ordered sources")
    _assert_private([item.model_dump(mode="json") for item in items])
    stale = [item.name for item in items if item.stale]
    unavailable = [item.name for item in items if not item.available]
    if len(unavailable) == len(items):
        overall = "UNAVAILABLE"
    elif stale and len(stale) + len(unavailable) == len(items):
        overall = "STALE"
    elif stale or unavailable:
        overall = "MIXED"
    else:
        overall = "FRESH"
    bundle = WorkspaceContextBundle(
        built_at=built_at, overall_freshness=overall,
        stale_sources=stale, unavailable_sources=unavailable,
        items=items, glossary=glossary,
    )
    encoded = json.dumps(bundle.model_dump(mode="json"), separators=(",", ":"), sort_keys=True)
    if len(encoded.encode("utf-8")) > maximum_bytes:
        raise ValueError("Workspace context exceeds safe size limit")
    return bundle


def serialize_context(bundle: WorkspaceContextBundle) -> str:
    return json.dumps(bundle.model_dump(mode="json"), separators=(",", ":"), sort_keys=True)
