from datetime import datetime, timezone
from dataclasses import replace
from unittest.mock import AsyncMock
import pytest
from tools.run_telegram_channel_schedule import due_slot, post_update, scheduled_minute
from notifications.chart import ChartSnapshot
from notifications.telegram_channel import TelegramChannelGateway, TelegramChannelConfig
from notifications.types import Notification, NotificationType


@pytest.mark.parametrize("utc_hour,label", [(5, "Morning"), (9, "Midday"), (15, "Evening"), (4, None), (16, None)])
def test_kampala_post_times(utc_hour, label):
    slot = due_slot(datetime(2026, 10, 5, utc_hour, 59, tzinfo=timezone.utc))
    assert (slot[1] if slot else None) == label


def test_randomized_slot_is_restart_stable_and_never_early():
    from datetime import date
    day = date(2026, 10, 5)
    minute = scheduled_minute(day, 8)
    assert 0 <= minute < 60
    assert scheduled_minute(day, 8) == minute
    assert due_slot(datetime(2026, 10, 5, 5, minute, tzinfo=timezone.utc))
    if minute:
        assert due_slot(datetime(2026, 10, 5, 5, minute - 1, tzinfo=timezone.utc)) is None
    assert len({scheduled_minute(date(2026, 10, d), 8) for d in range(1, 20)}) > 1


@pytest.mark.asyncio
async def test_unavailable_market_post_does_not_invent_prices(monkeypatch):
    import tools.run_telegram_channel_schedule as schedule
    monkeypatch.setattr(schedule, "read_market", lambda: (_ for _ in ()).throw(ValueError("stale")))
    channel = AsyncMock()
    await post_update(channel, datetime(2026, 10, 5, 5, tzinfo=timezone.utc), ("2026-10-05:8", "Morning"))
    event = channel.send.await_args.args[0]
    assert event.chart_snapshot is None
    assert "no price or signal published" in event.facts["Market"]
    assert event.event_id == "CHANNEL:2026-10-05:8"
    assert "JQE AI" in " ".join(schedule.EDUCATION)
    assert event.facts["Explore JQE"] == "https://jqe.jokiholdings.com"
    assert "https://t.me/jqetrading" in event.facts["Join & share"]


@pytest.mark.asyncio
async def test_channel_photo_uses_bytes_and_deduplicates_across_restart(tmp_path):
    config = TelegramChannelConfig("test-token", "@jqetrading", tmp_path / "claims.sqlite3")
    post, photo = AsyncMock(), AsyncMock()
    event = Notification(NotificationType.CHANNEL_UPDATE, "Market preview",
                         {"Market": "Closed-bar observation"}, event_id="daily:2026-10-05:8",
                         chart_snapshot=ChartSnapshot("chart.png", b"PNG-data"))
    for _ in range(2):
        channel = TelegramChannelGateway(config, post=post, photo_post=photo, sleep=AsyncMock())
        await channel.send(event)
        await channel.drain()
    post.assert_not_awaited()
    photo.assert_awaited_once()
    url, body, _ = photo.await_args.args
    assert url.endswith("/sendPhoto")
    assert b"PNG-data" in body and b"@jqetrading" in body
