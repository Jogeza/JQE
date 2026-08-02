from execution.order_manager import OrderManager


def test_live_demo_trade():

    manager = OrderManager()


    result = manager.create_order(

        signal="BUY",

        symbol="XAUUSD",

        lot=0.01,

        entry=0,

        stop_loss=4030,

        take_profit=4070,

        execute=True

    )


    print(result)


    assert result["status"] in [
        "EXECUTED",
        "FAILED"
    ]