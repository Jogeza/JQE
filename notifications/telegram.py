"""Minimal Telegram transport and authorization boundary."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from html import escape
from typing import Awaitable, Callable, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from notifications.types import Notification

MAX_TELEGRAM_MESSAGE = 4096


def daily_instrument_cap_message(*, instrument: str, count: int, limit: int, reset_at: str) -> str:
    """Dedicated operator message for a daily instrument submission block."""
    return (
        "<b>DAILY INSTRUMENT CAP REACHED</b>\n"
        f"Instrument: {escape(instrument)}\n"
        f"Submission starts: {count}/{limit}\n"
        f"Reset: {escape(reset_at)} UTC\n"
        "Action: New submissions for this instrument are blocked."
    )


class TelegramConfigurationError(ValueError):
    pass


class TelegramDeliveryError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class TelegramConfig:
    token: str = field(repr=False)
    chat_ids: tuple[int, ...] | int
    timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        if not self.token.strip():
            raise TelegramConfigurationError("Telegram token is missing")
        raw_chat_ids = (self.chat_ids,) if isinstance(self.chat_ids, int) else self.chat_ids
        if (
            not raw_chat_ids
            or any(isinstance(chat_id, bool) or not isinstance(chat_id, int) for chat_id in raw_chat_ids)
        ):
            raise TelegramConfigurationError("Telegram allowed chat is missing")
        object.__setattr__(self, "chat_ids", tuple(dict.fromkeys(raw_chat_ids)))
        if self.timeout_seconds <= 0 or self.timeout_seconds > 30:
            raise TelegramConfigurationError("Telegram timeout is invalid")


TelegramPost = Callable[[str, bytes, float], Awaitable[None]]


class TelegramGateway:
    def __init__(self, config: TelegramConfig, post: TelegramPost | None = None) -> None:
        self._config = config
        self._post = post or self._default_post

    async def send(self, notification: Notification) -> None:
        lines = [f"<b>{escape(notification.title)}</b>"]
        lines.extend(f"{escape(key)}: {escape(value)}" for key, value in notification.facts.items())
        await self.send_text("\n".join(lines))

    async def send_text(self, text: str) -> None:
        message = text[:MAX_TELEGRAM_MESSAGE]
        url = f"https://api.telegram.org/bot{self._config.token}/sendMessage"
        for chat_id in self._config.chat_ids:
            payload = json.dumps({
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "HTML",
            }).encode("utf-8")
            try:
                await self._post(url, payload, self._config.timeout_seconds)
            except Exception as exc:
                raise TelegramDeliveryError("Telegram delivery failed") from exc

    @staticmethod
    async def _default_post(url: str, payload: bytes, timeout: float) -> None:
        def send() -> None:
            request = Request(url, data=payload, method="POST", headers={"Content-Type": "application/json"})
            try:
                with urlopen(request, timeout=timeout) as response:
                    if not 200 <= int(response.status) < 300:
                        raise TelegramDeliveryError("Telegram delivery failed")
            except (HTTPError, URLError, TimeoutError) as exc:
                raise TelegramDeliveryError("Telegram delivery failed") from exc
        await asyncio.to_thread(send)


class TelegramReadModel(Protocol):
    async def get_system_status(self) -> object: ...
    async def get_risk_status(self) -> object: ...
    def get_execution_safety(self) -> object: ...
    async def get_execution_state(self) -> object: ...
    async def get_performance_summary(self) -> object: ...


class TelegramCommandProcessor:
    """Authorized read-only projection over injected JQE telemetry."""

    def __init__(self, allowed_chat_id: int, read_model: TelegramReadModel) -> None:
        self._allowed_chat_id = allowed_chat_id
        self._read_model = read_model

    async def process_update(self, update: object) -> str | None:
        if not isinstance(update, dict):
            return None
        message = update.get("message")
        if not isinstance(message, dict):
            return None
        chat = message.get("chat")
        text = message.get("text")
        if not isinstance(chat, dict) or chat.get("id") != self._allowed_chat_id:
            return None
        if not isinstance(text, str):
            return None
        command = text.strip().split(maxsplit=1)[0].split("@", maxsplit=1)[0].lower()
        if command == "/signal":
            return "SIGNAL\nLatest persisted signal: UNAVAILABLE"
        if command in {"/status", "/health"}:
            value = await self._read_model.get_system_status()
        elif command == "/risk":
            value = await self._read_model.get_risk_status()
        elif command == "/safety":
            value = self._read_model.get_execution_safety()
        elif command == "/positions":
            value = await self._read_model.get_execution_state()
        elif command == "/performance":
            value = await self._read_model.get_performance_summary()
        elif command == "/help":
            return "Commands: /status /health /signal /risk /safety /positions /performance"
        else:
            return None
        data = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
        return f"{command[1:].upper()}\n{json.dumps(data, sort_keys=True, default=str)[:4000]}"


def telegram_gateway_from_settings(settings: object) -> TelegramGateway | None:
    if not getattr(settings, "telegram_enabled", False):
        return None
    token = getattr(settings, "telegram_bot_token", None)
    chat_id = getattr(settings, "telegram_allowed_chat_id", None)
    if not isinstance(token, str) or not token.strip():
        raise TelegramConfigurationError("Telegram is enabled but its token is missing")
    if isinstance(chat_id, bool) or not isinstance(chat_id, int):
        raise TelegramConfigurationError("Telegram is enabled but its allowed chat is missing")
    return TelegramGateway(TelegramConfig(
        token=token,
        chat_ids=(chat_id,),
        timeout_seconds=getattr(settings, "telegram_request_timeout_seconds", 10.0),
    ))
