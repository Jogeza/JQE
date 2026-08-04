"""JQE Autonomous Market Scanner.

Scans a list of symbols and builds a consolidated market-state
snapshot for each, using the ``intelligence`` package's analyzers.

.. note::
    This scanner still calls ``core.market_data.MarketData`` directly
    rather than going through ``broker.base.BrokerGateway`` — a
    pre-existing gap documented in docs/architecture.md ("What's
    deliberately not touched"). It has no live caller today (see
    Milestone 1/2b's findings); migrating it onto ``BrokerGateway`` is
    still deferred to whichever milestone decides to build real
    trading logic on this pathway, not this one.
"""

from __future__ import annotations

from core.market_data import MarketData
from intelligence.market_state import MarketState
from intelligence.momentum_engine import MomentumEngine
from intelligence.trend_engine import TrendEngine
from intelligence.volatility_engine import VolatilityEngine

_DEFAULT_SYMBOLS = ["GOLD", "BTCUSD", "DOW30", "EURUSD"]
_SCAN_CANDLE_COUNT = 100


class MarketScanner:
    """Scans symbols and builds a market-state snapshot for each.

    Attributes:
        symbols: Symbols to scan.
    """

    def __init__(self, symbols: list[str] | None = None) -> None:
        self.symbols = symbols or list(_DEFAULT_SYMBOLS)

        self.data_engine = MarketData()
        self.state_engine = MarketState()
        self.trend_engine = TrendEngine()
        self.volatility_engine = VolatilityEngine()
        self.momentum_engine = MomentumEngine()

    def scan(self) -> list[dict]:
        """Scans all configured symbols. Alias for :meth:`autonomous_scan`."""
        return self.autonomous_scan()

    def autonomous_scan(self) -> list[dict]:
        """Builds a market-state snapshot for every configured symbol.

        Returns:
            One snapshot dict per symbol (see
            ``intelligence.market_state.MarketState.analyze``), in the
            same order as :attr:`symbols`. Symbols with no available
            market data get an ``"UNKNOWN"``/not-trade-ready snapshot
            rather than being skipped, so callers always get one
            result per requested symbol.
        """
        results = []

        for symbol in self.symbols:
            market_data = self.data_engine.get_market_data(symbol)

            if market_data is None:
                results.append(
                    {
                        "symbol": symbol,
                        "trend": "UNKNOWN",
                        "volatility": "UNKNOWN",
                        "momentum": "UNKNOWN",
                        "liquidity": "UNKNOWN",
                        "market_score": 0,
                        "trade_ready": False,
                    }
                )
                continue

            candles = self.data_engine.get_candles(symbol, _SCAN_CANDLE_COUNT)

            market_data["trend_analysis"] = self.trend_engine.analyze(candles)
            market_data["volatility_analysis"] = self.volatility_engine.analyze(candles)
            market_data["momentum_analysis"] = self.momentum_engine.analyze(candles)

            results.append(self.state_engine.analyze(market_data))

        return results
