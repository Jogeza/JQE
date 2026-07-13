from data.historical_data import HistoricalData
from strategy.features.indicators import Indicators
from strategy.features.feature_engine import FeatureEngine



database = HistoricalData()


data = database.load(
    "GOLD",
    "M15"
)



data = Indicators.add_all(
    data
)



engine = FeatureEngine()


market_features = engine.analyze(
    data
)


print(
    "JQE MARKET ANALYSIS"
)


print(
    market_features
)