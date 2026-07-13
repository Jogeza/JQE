from core.market_data import MarketData



def test_candle_data():


    data = MarketData()


    candles = data.get_candles(
        "GOLD",
        10
    )


    assert isinstance(
        candles,
        list
    )