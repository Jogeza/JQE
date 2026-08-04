"""JQE Market State Intelligence.

Combines trend, volatility, momentum, and liquidity analysis for a
symbol into one consolidated market-state snapshot with a legacy
confidence score.
"""

from __future__ import annotations

from intelligence.liquidity_engine import LiquidityEngine
from intelligence.market_score import MarketScore

#: MarketScore's scale is 0-100; this is the "ready to trade" cutoff
#: MarketState has always used.
_TRADE_READY_THRESHOLD = 70


class MarketState:
    """Builds a consolidated market-state snapshot for one symbol.

    Attributes:
        score_engine: Computes the legacy 0-100 confidence score from
            the classified trend/volatility/liquidity/momentum.
        liquidity_engine: Classifies liquidity from spread (Phase 3 —
            previously an inline threshold check in this class; see
            ``intelligence.liquidity_engine`` for why it was promoted).
    """

    def __init__(self) -> None:
        self.score_engine = MarketScore()
        self.liquidity_engine = LiquidityEngine()

    def analyze(self, market: dict | None) -> dict | None:
        """Builds a market-state snapshot from scanner data.

        Args:
            market: A dict with ``"symbol"``, ``"price"``, ``"spread"``,
                and (if already computed) ``"trend_analysis"``,
                ``"volatility_analysis"``, ``"momentum_analysis"``
                sub-dicts — as built by
                ``core.market_scanner.MarketScanner``.

        Returns:
            A consolidated snapshot dict, or ``None`` if ``market`` is
            ``None``.
        """
        if market is None:
            return None

        symbol = market["symbol"]

        trend_data = market.get("trend_analysis", {})
        trend = trend_data.get("trend", "UNKNOWN")

        volatility_data = market.get("volatility_analysis", {})
        volatility = volatility_data.get("volatility", "UNKNOWN")

        momentum_data = market.get("momentum_analysis", {})
        momentum = momentum_data.get("momentum", "UNKNOWN")

        liquidity_data = self.liquidity_engine.analyze(market.get("spread"))
        liquidity = liquidity_data["liquidity"]

        score = self.score_engine.calculate(trend, volatility, liquidity, momentum)

        return {
            "symbol": symbol,
            "trend": trend,
            "volatility": volatility,
            "momentum": momentum,
            "liquidity": liquidity,
            "market_score": score,
            "trade_ready": score >= _TRADE_READY_THRESHOLD,
            "price": market.get("price"),
            "atr": volatility_data.get("atr"),
            "rsi": momentum_data.get("rsi"),
        }
