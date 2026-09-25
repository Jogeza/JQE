"""Read-only chart snapshots used by outbound notifications.

The renderer accepts candles that have already been fetched by the active
cycle.  It deliberately performs no market-data or broker I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import base64
import math
import re
from typing import Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402


@dataclass(frozen=True, slots=True)
class ChartSnapshot:
    """An in-memory PNG plus an optional externally reachable image URL."""

    filename: str
    content: bytes
    media_type: str = "image/png"
    image_url: str | None = None

    @property
    def data_url(self) -> str:
        encoded = base64.b64encode(self.content).decode("ascii")
        return f"data:{self.media_type};base64,{encoded}"


def _field(candle: object, name: str) -> object:
    if isinstance(candle, dict):
        return candle[name]
    return getattr(candle, name)


def _safe_filename(symbol: str, timeframe: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", f"{symbol}_{timeframe}").strip("._")
    return f"{stem or 'jqe_signal'}.png"


def render_candlestick_snapshot(
    candles: Sequence[object],
    *,
    symbol: str,
    timeframe: str,
    entry_price: float | None = None,
    stop_loss: float | None = None,
    take_profit: float | None = None,
    max_candles: int = 80,
) -> ChartSnapshot:
    """Render recent candle context from an already-fetched candle sequence."""

    selected = list(candles[-max_candles:])
    if not selected:
        raise ValueError("cannot render a chart snapshot without candles")

    times = [_field(candle, "time") for candle in selected]
    opens = [float(_field(candle, "open")) for candle in selected]
    highs = [float(_field(candle, "high")) for candle in selected]
    lows = [float(_field(candle, "low")) for candle in selected]
    closes = [float(_field(candle, "close")) for candle in selected]
    values = (*opens, *highs, *lows, *closes)
    if not all(math.isfinite(value) and value > 0 for value in values):
        raise ValueError("chart candle prices must be positive and finite")

    fig, axis = plt.subplots(figsize=(10, 5), dpi=120)
    try:
        for index, (opening, high, low, close) in enumerate(zip(opens, highs, lows, closes)):
            rising = close >= opening
            color = "#2E8B57" if rising else "#D92D20"
            axis.vlines(index, low, high, color=color, linewidth=1.0, zorder=2)
            body_bottom = min(opening, close)
            body_height = max(abs(close - opening), max(abs(close), 1.0) * 1e-6)
            axis.add_patch(
                Rectangle(
                    (index - 0.3, body_bottom),
                    0.6,
                    body_height,
                    facecolor=color,
                    edgecolor=color,
                    linewidth=0.8,
                    zorder=3,
                )
            )

        reference_lines = (
            (entry_price, "Entry", "#2F80ED"),
            (stop_loss, "Stop loss", "#D92D20"),
            (take_profit, "Take profit", "#EAAA08"),
        )
        for price, label, color in reference_lines:
            if price is not None and math.isfinite(float(price)):
                axis.axhline(float(price), color=color, linestyle="--", linewidth=1.0, label=label)

        axis.set_title(f"{symbol} · {timeframe} · signal context")
        axis.set_xlim(-1, len(selected))
        axis.set_xticks([])
        axis.set_ylabel("Price")
        axis.grid(axis="y", alpha=0.2)
        handles, labels = axis.get_legend_handles_labels()
        if handles:
            axis.legend(handles, labels, loc="upper left", fontsize="small")
        fig.tight_layout()
        output = BytesIO()
        fig.savefig(output, format="png", facecolor="white")
        return ChartSnapshot(
            filename=_safe_filename(symbol, timeframe),
            content=output.getvalue(),
        )
    finally:
        plt.close(fig)
