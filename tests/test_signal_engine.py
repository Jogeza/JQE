from data.historical_data import HistoricalData

from strategy.features.indicators import Indicators

from strategy.features.feature_engine import FeatureEngine

from strategy.features.market_regime import MarketRegime

from strategy.signal_engine import SignalEngine



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



regime_engine = MarketRegime()


intelligence["regime"] = (
    regime_engine.detect(
        intelligence
    )
)



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