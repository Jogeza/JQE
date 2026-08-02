class TradeLifecycle:



    def process(
        self,
        signal,
        risk,
        order_manager,
        position_manager,
        symbol,
        price
    ):



        #
        # Risk approval
        #

        if risk["risk_percent"] <= 0:

            return {

                "status":
                "REJECTED",

                "reason":
                "Risk denied"

            }



        #
        # Create order
        #

        order = order_manager.create_order(

            signal,

            symbol,

            lot=0.01,

            entry=price,

            stop_loss=price - 10,

            take_profit=price + 20

        )



        if order["status"] == "REJECTED":

            return order



        #
        # Open position
        #

        position = (
            position_manager
            .open_position(order)
        )


        return {


            "status":
            "EXECUTED",


            "position":
            position

        }