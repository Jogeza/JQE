from core.market_data import MarketData


def test_live_xauusd_data():

    market = MarketData()

    candles = market.get_candles(
        symbol="XAUUSD",
        count=100
    )

    assert candles is not None
    assert len(candles) > 0

    print("\nLatest candles:")
    for candle in candles[-5:]:
        print(candle)