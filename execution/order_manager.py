class OrderManager:


    def create_order(
        self,
        signal,
        symbol,
        lot,
        entry,
        stop_loss,
        take_profit
    ):


        if signal != "BUY" and signal != "SELL":

            return {

                "status":"REJECTED",

                "reason":"Invalid signal"

            }



        order = {


            "symbol": symbol,


            "type": signal,


            "lot": lot,


            "entry": entry,


            "stop_loss": stop_loss,


            "take_profit": take_profit,


            "status":"CREATED"

        }


        return order