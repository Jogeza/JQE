"""Allowlisted, best-effort execution diagnostics."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from core.logger import logger


def log_unresolved_execution(
    *,
    idempotency_key: str,
    state: str,
    reconciliation: str | None = None,
    order_id: str | None = None,
    transaction_id: str | None = None,
    error_category: str | None = None,
) -> None:
    """Emit only non-secret execution evidence; logging cannot affect flow."""
    evidence: dict[str, Any] = {
        "idempotency_key": idempotency_key,
        "state": state,
        "reconciliation": reconciliation,
        "order_id": order_id,
        "transaction_id": transaction_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "error_category": error_category,
    }
    try:
        logger.warning("Unresolved execution: {}", evidence)
    except Exception:
        return
