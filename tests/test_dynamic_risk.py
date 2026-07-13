from risk.dynamic_risk import DynamicRisk

from risk.position_sizing import PositionSizing



intelligence = {


    "confidence":80,

    "regime":"TRENDING"

}



risk_engine = DynamicRisk()



risk = risk_engine.calculate(
    intelligence,
    balance=10000
)



print(
    "JQE RISK INTELLIGENCE"
)


print(risk)



sizer = PositionSizing()



lot = sizer.calculate_lot(

    risk_amount=risk["risk_amount"],

    stop_distance=50

)



print(
    "LOT SIZE:",
    lot
)