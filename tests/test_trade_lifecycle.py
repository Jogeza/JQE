from execution.order_manager import OrderManager

from execution.position_manager import PositionManager

from execution.trade_lifecycle import TradeLifecycle



order_manager = OrderManager()


position_manager = PositionManager()


lifecycle = TradeLifecycle()



risk = {


    "risk_percent":1.5

}



result = lifecycle.process(

    signal="BUY",

    risk=risk,

    order_manager=order_manager,

    position_manager=position_manager,

    symbol="GOLD",

    price=4000

)



print(
    "JQE TRADE LIFECYCLE"
)


print("===================")


print(result)