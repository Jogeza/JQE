"""
JQE Execution Simulator

Simulates broker execution.

Features:
- Order creation
- Spread simulation
- Slippage simulation
- Position tracking
- Balance updates
- Trade history
"""


from datetime import datetime
from core.logger import logger



class ExecutionSimulator:


    def __init__(
            self,
            balance=50
    ):

        self.balance = balance

        self.equity = balance

        self.positions = []

        self.history = []

        self.ticket = 0



    def create_order(
            self,
            symbol,
            direction,
            entry,
            lot,
            stop_loss,
            take_profit
    ):


        self.ticket += 1


        order_id = (
            f"JQE-{self.ticket:06d}"
        )


        # simulate execution delay/slippage

        slippage = 0.05


        if direction == "BUY":

            executed_price = (
                entry +
                slippage
            )


        else:

            executed_price = (
                entry -
                slippage
            )



        trade = {


            "ticket": order_id,


            "symbol": symbol,


            "direction": direction,


            "entry": round(
                executed_price,
                2
            ),


            "lot": lot,


            "stop_loss": stop_loss,


            "take_profit": take_profit,


            "open_time":
                datetime.now(),


            "status":
                "OPEN"

        }



        self.positions.append(
            trade
        )



        logger.info(

            f"ORDER OPENED {trade}"

        )


        return trade




    def close_position(
            self,
            ticket,
            exit_price
    ):


        for position in self.positions:


            if position["ticket"] == ticket:



                direction = position["direction"]


                entry = position["entry"]


                lot = position["lot"]



                if direction == "BUY":


                    points = (
                        exit_price -
                        entry
                    )


                else:


                    points = (
                        entry -
                        exit_price
                    )



                profit = (

                    points *
                    lot

                )



                self.balance += profit


                position["exit"] = exit_price

                position["profit"] = round(
                    profit,
                    2
                )

                position["status"] = "CLOSED"

                position["close_time"] = datetime.now()



                self.history.append(
                    position
                )



                self.positions.remove(
                    position
                )



                logger.info(

                    f"POSITION CLOSED {position}"

                )


                return position



        return None




    def account_status(self):


        return {


            "balance":
                round(
                    self.balance,
                    2
                ),


            "open_positions":
                len(
                    self.positions
                ),


            "closed_trades":
                len(
                    self.history
                )

        }