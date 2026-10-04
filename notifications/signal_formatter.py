"""Factual, HTML-safe trade alerts for an optional Telegram channel."""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape

from notifications.types import Notification, NotificationType


def render_signal_alert(notification: Notification) -> str:
    """Render only fields actually present in the event's broker/plan facts."""
    if notification.kind is NotificationType.CHANNEL_UPDATE:
        lines = [escape(notification.title)]
        for field in ("Session", "Market", "Observed at", "Did you know", "Explore JQE", "Join & share"):
            if notification.facts.get(field):
                lines.append(f"{field}: {escape(notification.facts[field])}")
        return "\n".join(lines + ["Explore with JQE ✨ Weltrade demo research; outcomes aren't guaranteed."])
    if notification.kind not in {
        NotificationType.POSITION_OPENED,
        NotificationType.POSITION_CLOSED,
        NotificationType.ORDER_REJECTED,
    }:
        raise ValueError("unsupported trade alert type")
    facts = notification.facts
    date = notification.occurred_at or datetime.now(timezone.utc)
    if date.tzinfo is None:
        raise ValueError("alert date must be timezone-aware")
    label = {
        NotificationType.POSITION_OPENED: "JQE ✨ Demo trade opened",
        NotificationType.POSITION_CLOSED: "JQE 📝 Trade wrapped up",
        NotificationType.ORDER_REJECTED: "JQE 🛑 Sitting this one out",
    }[notification.kind]
    title = f"{label} | {date.astimezone(timezone.utc).strftime('%d %b %Y').upper()}"
    if notification.simulated:
        title += " | SIMULATION"
    elif notification.demo_account or facts.get("Account mode", "").upper() == "DEMO":
        title += " | DEMO ACCOUNT"
    lines = [title, "BROKER: Weltrade"]

    asset = " ".join(part for part in (facts.get("Symbol"), facts.get("Timeframe")) if part)
    if asset:
        lines.append(f"ASSET: {escape(asset)}")
    direction = facts.get("Side") or facts.get("Direction")
    if direction:
        lines.append(f"ACTION | DIRECTION: {escape(direction)}")

    if notification.kind is NotificationType.POSITION_OPENED:
        for source, label in (("Entry", "ENTRY PRICE"), ("Stop loss", "STOP LOSS")):
            if facts.get(source):
                lines.append(f"{label}: {escape(facts[source])}")
        for index in range(1, 5):
            target = facts.get(f"TP{index}")
            if target:
                lines.append(f"TP{index}: {escape(target)}")
        if facts.get("Quantity"):
            lines.append(f"VOLUME: {escape(facts['Quantity'])}")
        if facts.get("Risk at stop %"):
            lines.append(f"RISK AT PLANNED STOP: {escape(facts['Risk at stop %'])}%")
    elif notification.kind is NotificationType.POSITION_CLOSED:
        for source, label in (("Exit", "EXIT PRICE"), ("Result", "RESULT"), ("Reason", "REASON")):
            if facts.get(source):
                lines.append(f"{label}: {escape(facts[source])}")
    else:
        if facts.get("Reason"):
            lines.append(f"REASON: {escape(facts['Reason'])}")

    lines.append("Watching the setup with you 👀 Demo update; outcomes aren't guaranteed.")
    return "\n".join(lines)
