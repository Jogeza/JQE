from analytics.trend_analysis import TrendAnalyzer




def test_trend_analysis():


    analyzer = TrendAnalyzer()



    candles = []



    price = 100



    for i in range(60):


        candles.append({

            "close": price + i,

            "open": price,

            "high": price + i + 1,

            "low": price - 1

        })



    result = analyzer.analyze(
        candles
    )



    assert "trend" in result

    assert result["trend"] == "BULLISH"