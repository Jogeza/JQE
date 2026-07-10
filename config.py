"""
JQE Configuration
"""


from dataclasses import dataclass


@dataclass
class TradingConfig:

    symbol: str = "XAUUSD"

    timeframe: int = 5

    risk_percent: float = 1.0

    max_daily_loss: float = 3.0

    max_trades_daily: int = 5



config = TradingConfig()