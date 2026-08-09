from execution.order_manager import OrderManager
from execution.position_manager import PositionManager
from execution.trade_lifecycle import TradeLifecycle


def test_execution_flow():

    order_manager = OrderManager()
    position_manager = PositionManager()
    lifecycle = TradeLifecycle()


    result = lifecycle.process(
        signal="BUY",
        risk={
            "risk_percent": 1
        },
        order_manager=order_manager,
        position_manager=position_manager,
        symbol="XAUUSD",
        price=4045.50,
        stop_loss=4035.0,
        take_profit=4065.0
    )


    print("\n===== JQE EXECUTION TEST =====")
    print(result)


    assert result["status"] == "EXECUTED"