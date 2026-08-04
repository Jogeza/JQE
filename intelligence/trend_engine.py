"""JQE Trend Engine.

Determines market direction from EMA20/EMA50 alignment relative to
current price.
"""

from __future__ import annotations


class TrendEngine:
    """Classifies market trend direction from closing prices."""

    def calculate_ema(self, prices: list[float], period: int) -> float | None:
        """Calculates a simple Exponential Moving Average.

        Args:
            prices: Closing prices, oldest to newest.
            period: EMA period.

        Returns:
            The EMA value, or ``None`` if there isn't enough data.
        """
        if len(prices) < period:
            return None

        multiplier = 2 / (period + 1)
        ema = prices[0]
        for price in prices[1:]:
            ema = (price - ema) * multiplier + ema

        return round(ema, 5)

    def analyze(self, candles: list[dict]) -> dict:
        """Determines market trend from a candle series.

        Args:
            candles: OHLC candles (dicts with a ``"close"`` key),
                oldest to newest.

        Returns:
            A dict with ``"trend"`` (``"BULLISH"``/``"BEARISH"``/
            ``"SIDEWAYS"``/``"UNKNOWN"``), ``"ema20"``, ``"ema50"``,
            and ``"price"``.
        """
        if len(candles) < 50:
            return {"trend": "UNKNOWN", "ema20": None, "ema50": None}

        closes = [candle["close"] for candle in candles]
        ema20 = self.calculate_ema(closes, 20)
        ema50 = self.calculate_ema(closes, 50)
        current_price = closes[-1]

        if ema20 > ema50 and current_price > ema20:
            trend = "BULLISH"
        elif ema20 < ema50 and current_price < ema20:
            trend = "BEARISH"
        else:
            trend = "SIDEWAYS"

        return {
            "trend": trend,
            "ema20": ema20,
            "ema50": ema50,
            "price": current_price,
        }
