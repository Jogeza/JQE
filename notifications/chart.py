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
    strategy_note: str | None = None,
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

    fig, axis = plt.subplots(figsize=(10, 5.6), dpi=120)
    try:
        # Match the dashboard's JQE wordmark and activity-line emblem.
        fig.text(0.065, 0.955, "JQE", fontsize=23, weight="bold", color="#182230", va="center")
        fig.text(0.155, 0.951, "ENGINE  |  WELTRADE DEMO RESEARCH", fontsize=9,
                 color="#475467", va="center")
        fig.add_artist(plt.Line2D([0.024, 0.034, 0.041, 0.048, 0.055],
                                 [0.954, 0.954, 0.968, 0.940, 0.954],
                                 transform=fig.transFigure, color="#0891B2", linewidth=2))
        axis.text(0.5, 0.55, "JQE", transform=axis.transAxes, ha="center", va="center",
                  fontsize=72, weight="bold", color="#182230", alpha=0.055, zorder=0)
        fig.text(0.065, 0.025, "jqe.jokiholdings.com  ·  @jqetrading", fontsize=9, color="#475467")
        fig.text(0.965, 0.025, "Research context · no guaranteed outcome", ha="right", fontsize=8, color="#667085")
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

        # Use the complete supplied closed-bar sequence for indicator warmup.
        import pandas as pd
        all_closes = pd.Series([float(_field(candle, "close")) for candle in candles])
        for span, color in ((50, "#7F56D9"), (200, "#0891B2")):
            if len(all_closes) >= span:
                ema = all_closes.ewm(span=span, adjust=False).mean().iloc[-len(selected):]
                axis.plot(range(len(selected)), ema, color=color, linewidth=1.2, label=f"EMA {span}")
        reference_lines = (
            (entry_price, "Entry", "#2F80ED"),
            (stop_loss, "Stop loss", "#D92D20"),
            (take_profit, "Take profit", "#EAAA08"),
        )
        for price, label, color in reference_lines:
            if price is not None and math.isfinite(float(price)):
                axis.axhline(float(price), color=color, linestyle="--", linewidth=1.0, label=label)

        axis.set_title(f"{symbol} · {timeframe} · Weltrade closed-bar strategy context")
        axis.set_xlim(-1, len(selected))
        indices = sorted(set((0, len(selected) // 2, len(selected) - 1)))
        axis.set_xticks(indices)
        axis.set_xticklabels([str(times[i]).replace('T', ' ')[:16] for i in indices], fontsize=8)
        axis.set_xlabel("Candle time · UTC")
        if strategy_note:
            axis.text(0.99, 0.02, strategy_note[:180], transform=axis.transAxes,
                      ha="right", va="bottom", fontsize=8,
                      bbox={"facecolor": "white", "alpha": 0.9, "edgecolor": "#ddd"})
        axis.set_ylabel("Price")
        axis.grid(axis="y", alpha=0.2)
        handles, labels = axis.get_legend_handles_labels()
        if handles:
            axis.legend(handles, labels, loc="upper left", fontsize="small")
        fig.tight_layout(rect=(0, 0.055, 1, 0.91))
        output = BytesIO()
        fig.savefig(output, format="png", facecolor="white")
        return ChartSnapshot(
            filename=_safe_filename(symbol, timeframe),
            content=output.getvalue(),
        )
    finally:
        plt.close(fig)
