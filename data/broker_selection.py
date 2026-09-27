"""Durable, SQLite-backed broker selection store and effective broker resolution."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Any

from core.exceptions import ConfigurationError

SUPPORTED_BROKERS: tuple[str, ...] = ("weltrade",)

_BROKER_NORMALIZATION: dict[str, str] = {
    "weltrade": "weltrade",
    "weltrade_demo": "weltrade",
}


def normalize_broker_name(broker: str) -> str:
    """Normalize broker identifiers to the canonical Weltrade form ('weltrade')."""
    clean = str(broker).strip().lower()
    if clean in _BROKER_NORMALIZATION:
        return _BROKER_NORMALIZATION[clean]
    raise ConfigurationError(
        f"Unsupported broker: '{broker}'. Supported options: {list(SUPPORTED_BROKERS)}"
    )


class BrokerSelectionStore:
    """Durable SQLite-backed store for operator broker selection."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute(
                """CREATE TABLE IF NOT EXISTS broker_selection (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    selected_broker TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    reason TEXT
                )"""
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=5.0)
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def get_selected_broker(self) -> str | None:
        """Return the currently persisted broker selection, or None if none set."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT selected_broker FROM broker_selection WHERE id = 1"
            ).fetchone()
        if row and row[0]:
            return normalize_broker_name(row[0])
        return None

    def set_selected_broker(self, broker: str, reason: str = "") -> str:
        """Persist a newly selected broker after canonical validation.

        Returns:
            The normalized canonical broker name.
        """
        canonical = normalize_broker_name(broker)
        now_str = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO broker_selection (id, selected_broker, updated_at, reason)
                VALUES (1, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    selected_broker = excluded.selected_broker,
                    updated_at = excluded.updated_at,
                    reason = excluded.reason
                """,
                (canonical, now_str, reason.strip() if reason else None),
            )
            conn.commit()
        return canonical


def get_effective_broker(active_settings: Any = None) -> str:
    """Resolve the authoritative active broker.

    Resolution order:
      1. Persisted operator selection in ``BrokerSelectionStore`` (authoritative).
      2. ``settings.broker`` configured via environment/.env (default ``weltrade``).

    Only Weltrade is a supported broker; this resolver never silently falls
    back to another broker and raises on any unsupported configuration.

    Raises:
        ConfigurationError: If the configured broker name is unsupported.
    """
    from config.settings import settings as default_settings

    active = active_settings or default_settings
    store_path = Path(
        getattr(active, "broker_selection_store_path", Path("state/broker_selection.sqlite3"))
    ).expanduser()
    if store_path.exists() and not store_path.is_file():
        raise ConfigurationError("Persisted broker selection path is not a file")
    if store_path.is_file():
        try:
            persisted = BrokerSelectionStore(store_path).get_selected_broker()
        except ConfigurationError:
            raise
        except Exception as exc:
            raise ConfigurationError("Persisted broker selection could not be read") from exc
        if persisted is not None:
            return persisted

    configured = getattr(active, "broker", "weltrade")
    return normalize_broker_name(configured)
