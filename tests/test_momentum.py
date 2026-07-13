from analytics.momentum import MomentumAnalyzer



def test_momentum_analysis():


    engine = MomentumAnalyzer()



    candles = []



    for i in range(40):


        candles.append({

            "open":100+i,

            "high":102+i,

            "low":99+i,

            "close":101+i

        })



    result = engine.analyze(

        candles

    )


    assert "momentum" in result

    assert result["rsi"] is not None