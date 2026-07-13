from analytics.market_score import MarketScore




def test_market_score():


    scorer = MarketScore()



    score = scorer.calculate(

        "BULLISH",

        "HIGH",

        "GOOD",

        "STRONG"

    )



    assert score == 100