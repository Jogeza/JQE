import pandas as pd


from core.decision_pipeline import DecisionPipeline





def test_decision_pipeline():


    data = []


    price = 100



    for i in range(250):


        data.append({

            "EMA_50": 110,

            "EMA_200": 100,

            "RSI_14": 70,

            "ATR_14": 1

        })



    df = pd.DataFrame(data)



    pipeline = DecisionPipeline()



    result = pipeline.analyze(

        df,

        "GOLD"

    )



    assert result["symbol"] == "GOLD"


    assert "decision" in result