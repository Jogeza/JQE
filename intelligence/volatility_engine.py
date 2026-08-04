"""JQE Volatility Engine.

Calculates market volatility using Average True Range (ATR).
"""

from __future__ import annotations


class VolatilityEngine:
    """Classifies market volatility from ATR."""

    def calculate_atr(self, candles: list[dict], period: int = 14) -> float | None:
        """Calculates Average True Range.

        Args:
            candles: OHLC candles (dicts with ``"high"``/``"low"``/
                ``"close"`` keys), oldest to newest.
            period: ATR lookback period.

        Returns:
            The ATR value, or ``None`` if there isn't enough data.
        """
        if len(candles) < period + 1:
            return None

        true_ranges = []
        for i in range(1, len(candles)):
            high = candles[i]["high"]
            low = candles[i]["low"]
            previous_close = candles[i - 1]["close"]
            true_ranges.append(
                max(high - low, abs(high - previous_close), abs(low - previous_close))
            )

        atr = sum(true_ranges[-period:]) / period
        return round(atr, 5)

    def analyze(self, candles: list[dict]) -> dict:
        """Classifies volatility from a candle series.

        Args:
            candles: OHLC candles, oldest to newest.

        Returns:
            A dict with ``"volatility"`` (``"HIGH"``/``"MEDIUM"``/
            ``"LOW"``/``"UNKNOWN"``) and ``"atr"``.
        """
        atr = self.calculate_atr(candles)
        if atr is None:
            return {"volatility": "UNKNOWN", "atr": None}

        # Simple adaptive classification.
        if atr > 20:
            level = "HIGH"
        elif atr > 5:
            level = "MEDIUM"
        else:
            level = "LOW"

        return {"volatility": level, "atr": atr}
