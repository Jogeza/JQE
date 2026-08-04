from intelligence.volatility_engine import VolatilityEngine


def test_volatility_analysis():

    analyzer = VolatilityEngine()

    candles = []

    for i in range(30):

        candles.append({"high": 120 + i, "low": 100 + i, "close": 110 + i})

    result = analyzer.analyze(candles)

    assert "volatility" in result

    assert result["atr"] is not None
