from data.historical_data import HistoricalData

from core.indicators import calculate_indicators
from intelligence.market_regime import detect_regime
from strategy.features.feature_engine import FeatureEngine
from strategy.signal_engine import SignalEngine



database = HistoricalData()



data = database.load(
    "GOLD",
    "M15"
)



data = calculate_indicators(data)



feature_engine = FeatureEngine()


intelligence = feature_engine.analyze(
    data
)


intelligence["regime"] = detect_regime(data)

signal_engine = SignalEngine()


signal = signal_engine.generate(
    intelligence
)



print(
    "JQE ADAPTIVE SIGNAL"
)


print(
    "=================="
)


print(
    intelligence
)


print()


print(
    signal
)