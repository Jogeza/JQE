import MetaTrader5 as mt5

from core.mt5_connection import connect


class OrderManager:

    def __init__(self):
        connect()


    def create_order(
        self,
        signal,
        symbol,
        lot,
        entry,
        stop_loss,
        take_profit,
        execute=False
    ):

        if signal not in ["BUY", "SELL"]:

            return {
                "status": "REJECTED",
                "reason": "Invalid signal"
            }


        order = {

            "symbol": symbol,
            "type": signal,
            "lot": lot,
            "entry": entry,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "status": "CREATED"

        }


        if execute:
            return self.send_order(order)


        return order



    def send_order(self, order):

        symbol = order["symbol"]


        tick = mt5.symbol_info_tick(symbol)


        if tick is None:

            return {

                "status": "FAILED",
                "reason": "No market tick"

            }



        if order["type"] == "BUY":

            order_type = mt5.ORDER_TYPE_BUY
            price = tick.ask


        else:

            order_type = mt5.ORDER_TYPE_SELL
            price = tick.bid



        request = {

            "action": mt5.TRADE_ACTION_DEAL,

            "symbol": symbol,

            "volume": order["lot"],

            "type": order_type,

            "price": price,

            "sl": order["stop_loss"],

            "tp": order["take_profit"],

            "deviation": 20,

            "magic": 20260802,

            "comment": "JQE Demo Execution",

            "type_time": mt5.ORDER_TIME_GTC,

            "type_filling": mt5.ORDER_FILLING_IOC

        }



        result = mt5.order_send(request)



        if result is None:

            return {

                "status": "FAILED",

                "reason": str(mt5.last_error()),

                "request": request

            }



        if result.retcode != mt5.TRADE_RETCODE_DONE:

            return {

                "status": "FAILED",

                "reason": result.comment,

                "retcode": result.retcode

            }



        return {

            "status": "EXECUTED",

            "order": result.order,

            "deal": result.deal,

            "price": result.price

        }