from data.historical_data import HistoricalData

from strategy.features.indicators import Indicators

from strategy.features.feature_engine import FeatureEngine

from strategy.features.market_regime import MarketRegime



database = HistoricalData()


data = database.load(
    "GOLD",
    "M15"
)



data = Indicators.add_all(
    data
)



engine = FeatureEngine()


features = engine.analyze(
    data
)



regime_engine = MarketRegime()


regime = regime_engine.detect(
    features
)



features["regime"] = regime



print(
    "JQE MARKET INTELLIGENCE"
)


print(
    "======================"
)


for key,value in features.items():

    print(
        f"{key}: {value}"
    )