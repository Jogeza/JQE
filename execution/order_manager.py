from __future__ import annotations

import asyncio

from broker.factory import get_gateway
from broker.types import OrderRequest, OrderSide


class OrderManager:
    """
    Broker-independent order execution manager.

    Execution flow:

        Strategy Signal
              |
              v
        OrderManager
              |
              v
        BrokerGateway
              |
              v
        MT5 / Deriv / Simulation
    """

    def __init__(self):
        self.gateway = get_gateway()

        # Connect broker gateway
        asyncio.run(
            self.gateway.connect()
        )


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

        side = (

            OrderSide.BUY

            if order["type"] == "BUY"

            else OrderSide.SELL

        )


        broker_order = OrderRequest(

            symbol=order["symbol"],

            side=side,

            volume=float(order["lot"]),

            stop_loss=float(order["stop_loss"])
            if order["stop_loss"]
            else None,

            take_profit=float(order["take_profit"])
            if order["take_profit"]
            else None

        )


        try:

            result = self._submit(
                broker_order
            )


            if result.status.value == "FILLED":

                return {

                    "status": "EXECUTED",

                    "order": result.order_id,

                    "price": result.filled_price,

                    "symbol": result.symbol,

                    "volume": result.volume

                }


            return {

                "status": "FAILED",

                "reason": result.raw

            }



        except Exception as e:

            return {

                "status": "FAILED",

                "reason": str(e)

            }



    def _submit(self, order):

        """
        Bridge synchronous OrderManager
        into async BrokerGateway.
        """

        return asyncio.run(

            self.gateway.submit_order(order)

        )