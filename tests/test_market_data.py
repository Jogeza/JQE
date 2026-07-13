from core.market_data import MarketData



def test_market_data():

    data = MarketData()


    result = data.get_market_data(
        "GOLD"
    )


    assert "symbol" in result

    assert "price" in result

    assert "spread" in result