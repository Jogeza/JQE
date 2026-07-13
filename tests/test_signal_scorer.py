from data.historical_data import HistoricalData

from strategy.features.indicators import Indicators

from strategy.features.feature_engine import FeatureEngine

from strategy.features.market_regime import MarketRegime

from strategy.signal_engine import SignalEngine

from strategy.scoring.signal_scorer import SignalScorer



database = HistoricalData()


data = database.load(
    "GOLD",
    "M15"
)



data = Indicators.add_all(
    data
)



feature_engine = FeatureEngine()


intelligence = feature_engine.analyze(
    data
)



regime = MarketRegime()


intelligence["regime"] = (
    regime.detect(
        intelligence
    )
)



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