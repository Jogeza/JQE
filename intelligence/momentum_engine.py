"""JQE Momentum Engine.

Calculates market momentum using RSI (Relative Strength Index).
"""

from __future__ import annotations


class MomentumEngine:
    """Classifies market momentum from RSI."""

    def calculate_rsi(self, candles: list[dict], period: int = 14) -> float | None:
        """Calculates RSI.

        Args:
            candles: OHLC candles (dicts with a ``"close"`` key),
                oldest to newest.
            period: RSI lookback period.

        Returns:
            The RSI value (0-100), or ``None`` if there isn't enough data.
        """
        if len(candles) < period + 1:
            return None

        closes = [candle["close"] for candle in candles]
        gains = []
        losses = []
        for i in range(1, len(closes)):
            change = closes[i] - closes[i - 1]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))

        average_gain = sum(gains[-period:]) / period
        average_loss = sum(losses[-period:]) / period

        if average_loss == 0:
            return 100

        rs = average_gain / average_loss
        rsi = 100 - (100 / (1 + rs))
        return round(rsi, 2)

    def analyze(self, candles: list[dict]) -> dict:
        """Classifies momentum from a candle series.

        Args:
            candles: OHLC candles, oldest to newest.

        Returns:
            A dict with ``"momentum"`` (``"STRONG"``/``"MODERATE"``/
            ``"WEAK"``/``"UNKNOWN"``) and ``"rsi"``.
        """
        rsi = self.calculate_rsi(candles)
        if rsi is None:
            return {"momentum": "UNKNOWN", "rsi": None}

        if rsi >= 60:
            momentum = "STRONG"
        elif rsi >= 45:
            momentum = "MODERATE"
        else:
            momentum = "WEAK"

        return {"momentum": momentum, "rsi": rsi}
