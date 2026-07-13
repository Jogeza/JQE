from data.market_loader import MarketLoader
from data.validator import DataValidator


loader = MarketLoader("XAUUSD")

loader.connect()

candles = loader.get_candles(
    count=100
)

print(candles.head())

DataValidator.check_missing(candles)

DataValidator.check_duplicates(candles)