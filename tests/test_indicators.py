from data.historical_data import HistoricalData
from strategy.features.indicators import Indicators



database = HistoricalData()


candles = database.load(
    "GOLD",
    "M15"
)


features = Indicators.add_all(
    candles
)


print(features.tail())


print("\nColumns:")
print(features.columns)