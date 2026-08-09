from data.historical_data import HistoricalData

from strategy.features.feature_engine import FeatureEngine
from intelligence.market_regime import detect_regime
from core.indicators import calculate_indicators
from strategy.scoring.signal_scorer import SignalScorer
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



scorer = SignalScorer()


result = scorer.evaluate(
    intelligence,
    signal
)



print(
    "JQE SIGNAL QUALITY"
)


print(
    "================="
)


print(result)