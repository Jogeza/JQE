"""Research-only quote replay with no candle-price or broker-fill substitution."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Sequence

from research.shadow_outcomes import SignalSpec


@dataclass(frozen=True, slots=True)
class TickQuote:
    time_msc: int
    bid: float
    ask: float

    @property
    def time(self) -> datetime:
        return datetime.fromtimestamp(self.time_msc / 1000, tz=timezone.utc)


@dataclass(frozen=True, slots=True)
class TickReplayOutcome:
    signal_id: str
    status: str
    entry_time: datetime | None
    entry_price: float | None
    outcome_time: datetime | None
    outcome_price: float | None
    net_r: float | None
    unresolved_reason: str | None
    entry_delay_ms: int | None
    timeout_delay_ms: int | None
    maximum_quote_gap_ms: int | None
    has_quote_gap: bool

    def to_dict(self) -> dict:
        row = asdict(self)
        for key in ("entry_time", "outcome_time"):
            if row[key] is not None:
                row[key] = row[key].isoformat()
        return row


def replay_buy_plan(
    spec: SignalSpec,
    quotes: Sequence[TickQuote],
    *,
    quote_gap_threshold_ms: int = 2_000,
) -> TickReplayOutcome:
    """Resolve a BUY using ask entry and the first subsequent bid exit quote."""
    if spec.side != "BUY":
        raise ValueError("tick replay currently accepts BUY plans only")
    valid = sorted((q for q in quotes if q.bid > 0 and q.ask >= q.bid), key=lambda q: q.time_msc)
    entry_boundary = int(spec.signal_close.timestamp() * 1000)
    horizon_boundary = entry_boundary + spec.horizon_bars * 60_000
    entry_index = next((i for i, q in enumerate(valid) if q.time_msc >= entry_boundary), None)
    if entry_index is None:
        return TickReplayOutcome(spec.signal_id, "UNRESOLVED", None, None, None, None, None,
                                 "entry quote unavailable", None, None, None, True)
    entry_quote = valid[entry_index]
    entry = entry_quote.ask
    risk = entry - spec.stop_loss
    if risk <= 0:
        return TickReplayOutcome(spec.signal_id, "UNRESOLVED", entry_quote.time, entry, None, None, None,
                                 "stop invalid for executable ask entry", entry_quote.time_msc-entry_boundary,
                                 None, None, entry_quote.time_msc-entry_boundary > quote_gap_threshold_ms)
    path = [q for q in valid[entry_index:] if q.time_msc <= horizon_boundary]
    gaps = [b.time_msc-a.time_msc for a, b in zip(path, path[1:])]
    max_gap = max(gaps, default=0)
    entry_delay = entry_quote.time_msc - entry_boundary
    for quote in path:
        if quote.bid <= spec.stop_loss:
            return TickReplayOutcome(
                spec.signal_id, "SL", entry_quote.time, entry, quote.time, quote.bid,
                (quote.bid-entry)/risk, None, entry_delay, None, max_gap,
                entry_delay > quote_gap_threshold_ms or max_gap > quote_gap_threshold_ms,
            )
        if quote.bid >= spec.take_profit:
            return TickReplayOutcome(
                spec.signal_id, "TP", entry_quote.time, entry, quote.time, quote.bid,
                (quote.bid-entry)/risk, None, entry_delay, None, max_gap,
                entry_delay > quote_gap_threshold_ms or max_gap > quote_gap_threshold_ms,
            )
    timeout = next((q for q in valid[entry_index:] if q.time_msc >= horizon_boundary), None)
    if timeout is None:
        return TickReplayOutcome(spec.signal_id, "UNRESOLVED", entry_quote.time, entry, None, None, None,
                                 "timeout quote unavailable", entry_delay, None, max_gap, True)
    timeout_delay = timeout.time_msc - horizon_boundary
    return TickReplayOutcome(
        spec.signal_id, "TIMEOUT", entry_quote.time, entry, timeout.time, timeout.bid,
        (timeout.bid-entry)/risk, None, entry_delay, timeout_delay, max_gap,
        entry_delay > quote_gap_threshold_ms or timeout_delay > quote_gap_threshold_ms or max_gap > quote_gap_threshold_ms,
    )
