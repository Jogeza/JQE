"""Owner-authorized channel posts at varied minutes in three Kampala hours."""
import argparse
import asyncio
from datetime import datetime, timedelta, timezone
import json
import hashlib
import os
from pathlib import Path
from urllib.request import urlopen
from urllib.parse import urlencode

from config.settings import settings
from notifications.chart import render_candlestick_snapshot
from notifications.telegram_channel import telegram_channel_from_settings
from notifications.types import Notification, NotificationType

KAMPALA = timezone(timedelta(hours=3), "Africa/Kampala")
SLOTS = {8: "Morning", 12: "Midday", 18: "Evening"}
EDUCATION = (
    "JQE AI helps you explore market research and ask questions about evidence. Treat its answers as research assistance, not guaranteed trading outcomes.",
    "JQE Engine journals decisions and their reasons, including NO_TRADE. Explore how research becomes a guarded demo decision.",
    "JQE pairs Weltrade chart observations with research tools. Data provenance and freshness matter more than a green connection badge.",
    "JQE research reviews can include costs, chronological holdouts and uncertainty. Journaling does not automatically retrain the strategy.",
    "JQE AI is available in the hosted dashboard for research questions. Broker execution follows separate demo risk and safety checks.",
)


def scheduled_minute(day, hour):
    # Stable across restarts, varied across dates and slots; no extra daily posts.
    digest = hashlib.sha256(f"jqetrading:{day}:{hour}".encode()).digest()
    return int.from_bytes(digest[:4], "big") % 60


def due_slot(now):
    local = now.astimezone(KAMPALA)
    if local.hour in SLOTS and local.minute >= scheduled_minute(local.date(), local.hour):
        return f"{local.date()}:{local.hour}", SLOTS[local.hour]
    return None


def read_market(symbol="FX Vol 20"):
    query = urlencode({"symbol": symbol, "timeframe": "M5", "count": 250})
    with urlopen("http://127.0.0.1:8000/api/v1/market/candles?" + query, timeout=20) as response:
        body = response.read(2_000_001)
    if len(body) > 2_000_000:
        raise ValueError("Market response too large")
    data = json.loads(body)
    if data.get("stale") is not False or data.get("degraded") is not False or data.get("market_data_source") != "BROKER":
        raise ValueError("Fresh broker candles unavailable")
    return data


async def post_position_preview(channel, now):
    def load():
        with urlopen("http://127.0.0.1:8000/api/v1/execution", timeout=20) as response:
            execution = json.load(response)
        if execution.get("connected") is not True or not execution.get("positions"):
            raise ValueError("No current verified broker position to illustrate")
        position = execution["positions"][0]
        return position, read_market(position["symbol"])
    position, data = await asyncio.to_thread(load)
    snapshot = await asyncio.to_thread(render_candlestick_snapshot, data["candles"],
        symbol=position["symbol"], timeframe="M5", entry_price=position["open_price"],
        stop_loss=position.get("stop_loss"), take_profit=position.get("take_profit"),
        strategy_note=f"{position['side']} · existing demo position · broker entry / SL / TP · not a new signal")
    facts = {"Session": "Existing guarded-demo position review · not a new entry signal",
             "Market": f"{position['symbol']} M5 · {position['side']} · broker entry {position['open_price']} · SL {position.get('stop_loss')} · TP {position.get('take_profit')}",
             "Observed at": execution_time(data, now),
             "Did you know": "Entry, stop-loss and target lines show the broker position's current levels, not a guaranteed outcome."}
    await channel.send(Notification(NotificationType.CHANNEL_UPDATE, "JQE · Annotated demo position",
        facts, occurred_at=now, chart_snapshot=snapshot,
        event_id=f"POSITION_PREVIEW:{position['id']}:{now.isoformat()}", demo_account=True))
    await channel.drain()


def execution_time(data, now):
    return str(data.get("observed_at") or now.isoformat())


async def post_update(channel, now, slot, *, preview=False):
    key, label = slot
    local = now.astimezone(KAMPALA)
    facts = {"Session": f"{label} · {local:%d %b %Y %H:%M} Kampala",
             "Did you know": EDUCATION[(local.toordinal() + local.hour) % len(EDUCATION)],
             "Explore JQE": "https://jqe.jokiholdings.com",
             "Join & share": "Research updates and annotated demo charts: https://t.me/jqetrading"}
    snapshot = None
    try:
        data = await asyncio.to_thread(read_market)
        candles = data["candles"]
        facts["Market"] = f"FX Vol 20 M5 · latest closed-bar close {candles[-1]['close']} · BROKER / CURRENT"
        facts["Observed at"] = str(data.get("observed_at") or now.isoformat())
        snapshot = await asyncio.to_thread(render_candlestick_snapshot, candles,
            symbol="FX Vol 20", timeframe="M5", strategy_note="EMA trend context · observation only · no entry signal")
    except Exception:
        facts["Market"] = "Fresh workstation evidence unavailable; no price or signal published."
    await channel.send(Notification(NotificationType.CHANNEL_UPDATE,
        "JQE · Market notes & Did you know?" + (" · PREVIEW" if preview else ""), facts,
        occurred_at=now, chart_snapshot=snapshot, event_id=f"CHANNEL:{key}", demo_account=True))
    await channel.drain()


async def run(preview=False, position_preview=False):
    channel = telegram_channel_from_settings(settings)
    if channel is None or settings.telegram_channel_chat_id != "@jqetrading":
        raise RuntimeError("Explicit @jqetrading channel configuration required")
    now = datetime.now(timezone.utc)
    if position_preview:
        await post_position_preview(channel, now)
        return
    if preview:
        await post_update(channel, now, (f"preview:{now.isoformat()}", "Preview"), preview=True)
        return
    path = Path("state/telegram_channel_schedule.json")
    last_slot = None
    while True:
        now = datetime.now(timezone.utc)
        slot = due_slot(now)
        if slot and slot[0] != last_slot:
            await post_update(channel, now, slot)
            last_slot = slot[0]
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"pid": os.getpid(), "updated_at": now.isoformat(),
            "status": "RUNNING", "timezone": "Africa/Kampala", "hours": list(SLOTS)}))
        temporary.replace(path)
        await asyncio.sleep(60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--position-preview", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(args.preview, args.position_preview))
