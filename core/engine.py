"""JQE institutional trading engine.

High-level composition root that wires together market scanning,
portfolio state, and the trade-decisioning pipeline. This is the object
higher-level entry points (a live trading loop, a dashboard, a future
API) use to get programmatic access to JQE's core capabilities without
needing to know how scanning/decisioning are implemented.
"""

from __future__ import annotations

from typing import Any

from core.decision_pipeline import DecisionPipeline
from core.logger import logger
from core.market_scanner import MarketScanner
from core.portfolio import Portfolio


class JQEEngine:
    """Composition root for JQE's market scanning and decisioning core.

    Attributes:
        portfolio: Tracks currently held positions.
        pipeline: Evaluates signals, scores, and risk into trade decisions.
    """

    def __init__(self) -> None:
        self.portfolio = Portfolio()
        self.pipeline = DecisionPipeline()

    def start(self) -> None:
        """Logs engine startup. Call once before using the engine."""
        logger.info("JQE institutional core engine online")

    def scan_markets(self, symbols: list[str]) -> Any:
        """Scans the given symbols for tradable opportunities.

        Args:
            symbols: Ticker symbols to scan.

        Returns:
            The scanner's result set. See
            :class:`core.market_scanner.MarketScanner`.
        """
        scanner = MarketScanner(symbols)
        return scanner.scan()

    def evaluate_trade(self, signal: Any, score: Any, risk: Any) -> Any:
        """Evaluates a candidate trade through the decision pipeline.

        Args:
            signal: Strategy signal payload.
            score: Signal confidence/score payload.
            risk: Risk context payload.

        Returns:
            The pipeline's decision. See
            :class:`core.decision_pipeline.DecisionPipeline`.
        """
        return self.pipeline.decide(signal, score, risk)
