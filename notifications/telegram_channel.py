"""Optional, process-armed Telegram channel observer with durable deduplication."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sqlite3
from typing import Awaitable, Callable
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from core.logger import logger
from notifications.signal_formatter import render_signal_alert
from notifications.types import Notification, NotificationType


Post = Callable[[str, bytes, float], Awaitable[None]]
Sleep = Callable[[float], Awaitable[None]]
_CHANNEL_KINDS = {
    NotificationType.POSITION_OPENED,
    NotificationType.POSITION_CLOSED,
    NotificationType.ORDER_REJECTED,
}
_cached_gateway: TelegramChannelGateway | None = None
_cached_key: bytes | None = None


@dataclass(frozen=True, slots=True)
class TelegramChannelConfig:
    token: str = field(repr=False)
    chat_id: str = field(repr=False)
    claim_store_path: Path
    timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        if not self.token.strip():
            raise ValueError("Telegram channel token is missing")
        if not re.fullmatch(r"(?:-100\d+|@[A-Za-z][A-Za-z0-9_]{4,31})", self.chat_id):
            raise ValueError("Telegram channel destination is invalid")


class TelegramChannelGateway:
    """Enqueue quickly; claim and deliver on an isolated bounded worker."""

    def __init__(self, config: TelegramChannelConfig, *, post: Post | None = None,
                 sleep: Sleep = asyncio.sleep, queue_limit: int = 32) -> None:
        if queue_limit < 1:
            raise ValueError("Telegram channel queue limit must be positive")
        self._config = config
        self._post = post or self._default_post
        self._sleep = sleep
        self._queue: asyncio.Queue[Notification] = asyncio.Queue(maxsize=queue_limit)
        self._worker: asyncio.Task[None] | None = None

    async def send(self, notification: Notification) -> bool:
        if notification.kind not in _CHANNEL_KINDS or not notification.event_id:
            return False
        try:
            self._queue.put_nowait(notification)
        except asyncio.QueueFull:
            logger.warning("Telegram channel alert queue full; event not queued")
            return False
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._run())
            self._worker.add_done_callback(self._restart_if_queued)
        return False  # Enqueued is not proof of Telegram delivery.

    def _restart_if_queued(self, task: asyncio.Task[None]) -> None:
        if not task.cancelled() and not self._queue.empty():
            self._worker = asyncio.create_task(self._run())
            self._worker.add_done_callback(self._restart_if_queued)

    def _claim_once(self, notification: Notification) -> bool:
        path = self._config.claim_store_path
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path, timeout=5) as connection:
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("""CREATE TABLE IF NOT EXISTS telegram_channel_claims (
                destination TEXT NOT NULL, kind TEXT NOT NULL, event_id TEXT NOT NULL,
                claimed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(destination, kind, event_id)
            )""")
            return connection.execute(
                "INSERT OR IGNORE INTO telegram_channel_claims(destination,kind,event_id) VALUES(?,?,?)",
                (self._config.chat_id, notification.kind.value, notification.event_id),
            ).rowcount == 1

    async def _run(self) -> None:
        while not self._queue.empty():
            notification = await self._queue.get()
            try:
                if not await asyncio.to_thread(self._claim_once, notification):
                    continue
                text = render_signal_alert(notification)
                payload = json.dumps({
                    "chat_id": self._config.chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                }).encode("utf-8")
                url = f"https://api.telegram.org/bot{self._config.token}/sendMessage"
                for attempt in range(3):
                    try:
                        await self._post(url, payload, self._config.timeout_seconds)
                        break
                    except Exception as exc:
                        if getattr(exc, "code", getattr(exc, "status_code", None)) == 429 and attempt < 2:
                            headers = getattr(exc, "headers", None)
                            retry_after = headers.get("Retry-After", "1") if headers else "1"
                            try:
                                delay = min(5.0, max(0.1, float(retry_after)))
                            except (TypeError, ValueError):
                                delay = 1.0
                            await self._sleep(delay)
                            continue
                        logger.warning("Telegram channel alert delivery failed")
                        break
                await self._sleep(0.1)  # Bounded worker rate; never in the trading path.
            except Exception:
                logger.warning("Telegram channel alert processing failed")
            finally:
                self._queue.task_done()

    async def drain(self) -> None:
        """Wait for queued work in offline tests and orderly shutdown only."""
        await self._queue.join()

    @staticmethod
    async def _default_post(url: str, payload: bytes, timeout: float) -> None:
        def post() -> None:
            request = Request(url, data=payload, method="POST", headers={"Content-Type": "application/json"})
            with urlopen(request, timeout=timeout) as response:
                if not 200 <= int(response.status) < 300:
                    raise RuntimeError("Telegram channel response was unsuccessful")
        await asyncio.to_thread(post)


def telegram_channel_from_settings(settings: object) -> TelegramChannelGateway | None:
    # Settings also reads .env; only an explicit process environment flag arms
    # this optional public destination.
    if os.environ.get("JQE_TELEGRAM_CHANNEL_ENABLED", "").strip().lower() != "true":
        return None
    if getattr(settings, "telegram_channel_enabled", False) is not True:
        return None
    token = getattr(settings, "telegram_bot_token", None)
    chat_id = getattr(settings, "telegram_channel_chat_id", None)
    if not isinstance(token, str) or not isinstance(chat_id, str):
        raise ValueError("Telegram channel configuration is incomplete")
    config = TelegramChannelConfig(
        token=token, chat_id=chat_id,
        claim_store_path=Path(getattr(settings, "telegram_channel_claim_store_path")),
        timeout_seconds=float(getattr(settings, "telegram_request_timeout_seconds", 10.0)),
    )
    # main.run constructs notification services per watchlist pair. One
    # process-wide worker enforces the same bounded queue and send rate.
    global _cached_gateway, _cached_key
    key = sha256(f"{token}\0{chat_id}\0{config.claim_store_path}\0{config.timeout_seconds}".encode()).digest()
    if _cached_gateway is None or _cached_key != key:
        _cached_gateway = TelegramChannelGateway(config)
        _cached_key = key
    return _cached_gateway
