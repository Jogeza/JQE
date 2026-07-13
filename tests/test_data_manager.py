from data.data_manager import DataManager


manager = DataManager()


manager.collect(
    symbol="XAUUSD",
    timeframe="M15",
    candles=500
)


manager.collect(
    symbol="DOW.N",
    timeframe="M15",
    candles=500
)


manager.collect(
    symbol="BTCUSD",
    timeframe="H1",
    candles=500
)


print("JQE DATA ENGINE COMPLETE")