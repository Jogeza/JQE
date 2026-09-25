from __future__ import annotations

import sqlite3
from types import SimpleNamespace

from api.notifications import get_notification_status


def _settings(path, **overrides):
    values = {
        "telegram_enabled": False,
        "telegram_bot_token": None,
        "telegram_allowed_chat_id": None,
        "slack_webhook_url": None,
        "observation_evidence_path": path,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_notification_status_is_safe_when_channels_are_disabled(monkeypatch, tmp_path):
    import api.notifications as notifications_api

    monkeypatch.setattr(
        notifications_api, "settings", _settings(tmp_path / "missing.sqlite3")
    )

    response = get_notification_status()

    assert [(item.channel, item.state) for item in response.channels] == [
        ("telegram", "DISABLED"),
        ("slack", "DISABLED"),
    ]
    assert response.daily_digest.state == "UNAVAILABLE"


def test_notification_status_reads_daily_digest_observation(monkeypatch, tmp_path):
    import api.notifications as notifications_api

    path = tmp_path / "evidence.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE digest_sent_log (utc_date TEXT PRIMARY KEY, sent_at TEXT NOT NULL)"
        )
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        connection.execute(
            "INSERT INTO digest_sent_log VALUES (?, ?)",
            (now.date().isoformat(), now.isoformat()),
        )
    monkeypatch.setattr(
        notifications_api,
        "settings",
        _settings(path, telegram_enabled=True, telegram_bot_token="configured", telegram_allowed_chat_id=1),
    )

    response = get_notification_status()

    assert response.channels[0].state == "READY"
    assert response.daily_digest.state == "SENT"
