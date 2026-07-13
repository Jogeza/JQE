from data.data_manager import DataManager


manager = DataManager()


manager.collect(
    symbol="GOLD",
    timeframe="M15",
    candles=500
)


manager.collect(
    symbol="DOW30",
    timeframe="M15",
    candles=500
)


manager.collect(
    symbol="BITCOIN",
    timeframe="H1",
    candles=500
)


print("JQE DATA ENGINE COMPLETE")