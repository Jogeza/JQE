"""Minimal Telegram transport and authorization boundary."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from html import escape
from datetime import datetime, timezone
from typing import Awaitable, Callable, Protocol, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from notifications.types import DigestSnapshot, Notification, NotificationType

MAX_TELEGRAM_MESSAGE = 4096


InstrumentDigestSnapshot = DigestSnapshot


_TELEGRAM_EMOJI = {
    NotificationType.ORDER_REJECTED: "❌",
    NotificationType.TRADE_BLOCKED: "❌",
    NotificationType.PAPER_TRADE_BLOCKED: "❌",
    NotificationType.DERIV_IDENTITY_REJECTED: "❌",
    NotificationType.POSITION_OPENED: "✅",
    NotificationType.POSITION_MODIFIED: "✅",
    NotificationType.POSITION_CLOSED: "✅",
    NotificationType.PAPER_POSITION_OPENED: "✅",
    NotificationType.PAPER_POSITION_CLOSED: "✅",
    NotificationType.DERIV_IDENTITY_VERIFIED: "✅",
    NotificationType.EMERGENCY_STOP: "⚠️",
    NotificationType.RUNTIME_HEALTH: "⚠️",
    NotificationType.PAPER_RUNTIME_ERROR: "⚠️",
    NotificationType.DAILY_DIGEST: "📊",
    NotificationType.PAPER_PERFORMANCE: "📊",
    NotificationType.BROKER_CONNECTION: "🔌",
}


def _is_numeric_like(value: str) -> bool:
    v = value.strip().rstrip("%").lstrip("$").lstrip("+-")
    if not v:
        return False
    try:
        float(v)
        return True
    except ValueError:
        pass
    if "/" in v:
        parts = v.split("/")
        if len(parts) == 2:
            try:
                float(parts[0].strip())
                float(parts[1].strip())
                return True
            except ValueError:
                pass
    if v.upper().endswith("R"):
        try:
            float(v[:-1].strip())
            return True
        except ValueError:
            pass
    return False


def _telegram_value(key: str, value: str) -> str:
    escaped = escape(value)
    numeric_keys = (
        "price", "loss", "profit", "risk", "volume", "count", "limit", "cap",
        "p/l", "sl", "tp", "entry", "exit", "balance", "drawdown", "spread",
        "atr", "age", "starts", "score",
    )
    return (
        f"<code>{escaped}</code>"
        if any(token in key.lower() for token in numeric_keys) or _is_numeric_like(value)
        else escaped
    )


def render_telegram(notification: Notification) -> str:
    emoji = _TELEGRAM_EMOJI.get(notification.kind, "ℹ️")
    if notification.kind is NotificationType.DAILY_DIGEST:
        digest = format_daily_digest(notification.digest_snapshots, as_of=notification.occurred_at)
        return f"{emoji} {digest}"
    lines = [f"{emoji} <b>{escape(notification.title)}</b>"]
    lines.extend(
        f"<b>{escape(key)}:</b> {_telegram_value(key, value)}"
        for key, value in notification.facts.items()
    )
    return "\n".join(lines)


def format_daily_digest(
    items: Sequence[InstrumentDigestSnapshot],
    *,
    as_of: datetime | None = None,
) -> str:
    """Format once-daily summary across all active watchlist instruments."""
    now = as_of or datetime.now(timezone.utc)
    utc_date = now.strftime("%Y-%m-%d")
    lines = [
        "<b>DAILY MARKET &amp; WATCHLIST DIGEST</b>",
        f"Date: {utc_date} UTC",
        f"Active Instruments: {len(items)}",
        "",
    ]
    if not items:
        lines.append("No active instruments on the watchlist.")
        return "\n".join(lines)
    for item in items:
        steady_label = "YES (STEADY)" if item.is_steady else "NO (UNSTEADY)"
        score_val = f"{item.quality_score:.0f}" if isinstance(item.quality_score, (int, float)) else "N/A"
        lines.extend([
            f"<b>{escape(item.symbol)} ({escape(item.timeframe)})</b>",
            f"• Conclusion: {escape(item.conclusion)}",
            f"• Quality Score: {score_val}",
            f"• Steady / Worth Trading: {steady_label}",
            f"• Daily Cap Usage: {item.cap_count}/{item.cap_limit}",
            "",
        ])
    return "\n".join(lines).strip()


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
        await self.send_text(render_telegram(notification))

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


class TelegramWatchlistModel(Protocol):
    def get_items(self) -> Sequence[object]: ...
    def add_item(self, symbol: str, timeframe: str = "H1") -> object: ...
    def remove_item(self, symbol: str, timeframe: str | None = None) -> bool: ...


class TelegramDigestProvider(Protocol):
    async def get_digest_snapshots(self) -> Sequence[InstrumentDigestSnapshot]: ...


class TelegramDigestService:
    """Dispatches once-daily digests to the configured Telegram chat."""

    def __init__(self, gateway: TelegramGateway, provider: TelegramDigestProvider) -> None:
        self._gateway = gateway
        self._provider = provider

    async def send_digest(self, as_of: datetime | None = None) -> str:
        snapshots = await self._provider.get_digest_snapshots()
        message = format_daily_digest(snapshots, as_of=as_of)
        await self._gateway.send_text(message)
        return message


class TelegramCommandProcessor:
    """Authorized read-only projection over injected JQE telemetry."""

    def __init__(
        self,
        allowed_chat_id: int,
        read_model: TelegramReadModel,
        watchlist_model: TelegramWatchlistModel | None = None,
        digest_provider: TelegramDigestProvider | None = None,
    ) -> None:
        self._allowed_chat_id = allowed_chat_id
        self._read_model = read_model
        self._watchlist_model = watchlist_model
        self._digest_provider = digest_provider

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
        elif command == "/watchlist":
            if self._watchlist_model is None:
                return "WATCHLIST\nStore unavailable"
            items = self._watchlist_model.get_items()
            if not items:
                return "WATCHLIST: (empty)"
            lines = [f"WATCHLIST ({len(items)} instruments):"]
            for item in items:
                sym = getattr(item, "symbol", str(item))
                tf = getattr(item, "timeframe", "H1")
                lines.append(f"• {sym} ({tf})")
            return "\n".join(lines)
        elif command == "/add":
            if self._watchlist_model is None:
                return "WATCHLIST\nStore unavailable"
            parts = text.strip().split(maxsplit=1)
            if len(parts) < 2 or not parts[1].strip():
                return "Usage: /add <symbol> [timeframe] (e.g. /add FX Vol 20 H1 or /add R_75:H1)"
            arg = parts[1].strip()
            if ":" in arg:
                sym, tf = arg.rsplit(":", 1)
            elif " " in arg and arg.rsplit(maxsplit=1)[1].upper() in {"M1", "M5", "M15", "M30", "H1", "H4", "D1"}:
                sym, tf = arg.rsplit(maxsplit=1)
            else:
                sym, tf = arg, "H1"
            try:
                item = self._watchlist_model.add_item(sym, tf)
                item_sym = getattr(item, "symbol", sym.upper())
                item_tf = getattr(item, "timeframe", tf.upper())
                return f"ADDED TO WATCHLIST: {item_sym} ({item_tf})"
            except ValueError as exc:
                return f"ERROR: {exc}"
        elif command == "/remove":
            if self._watchlist_model is None:
                return "WATCHLIST\nStore unavailable"
            parts = text.strip().split(maxsplit=1)
            if len(parts) < 2 or not parts[1].strip():
                return "Usage: /remove <symbol> [timeframe] (e.g. /remove FX Vol 20 or /remove R_75:H1)"
            arg = parts[1].strip()
            if ":" in arg:
                sym, tf = arg.rsplit(":", 1)
            elif " " in arg and arg.rsplit(maxsplit=1)[1].upper() in {"M1", "M5", "M15", "M30", "H1", "H4", "D1"}:
                sym, tf = arg.rsplit(maxsplit=1)
            else:
                sym, tf = arg, None
            try:
                removed = self._watchlist_model.remove_item(sym, tf)
                tf_str = f" ({tf.upper()})" if tf else ""
                if removed:
                    return f"REMOVED FROM WATCHLIST: {sym.upper()}{tf_str}"
                return f"NOT FOUND ON WATCHLIST: {sym.upper()}{tf_str}"
            except ValueError as exc:
                return f"ERROR: {exc}"
        elif command == "/digest":
            if self._digest_provider is None:
                return "DIGEST\nDigest provider unavailable"
            snapshots = await self._digest_provider.get_digest_snapshots()
            return format_daily_digest(snapshots)
        elif command == "/help":
            return (
                "Commands: /status /health /signal /risk /safety /positions /performance "
                "/watchlist /add <sym> [tf] /remove <sym> [tf] /digest"
            )
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
