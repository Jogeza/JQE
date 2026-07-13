"""
JQE Institutional Backtesting Engine
Version 0.1.0
"""


from risk.risk_controller import approve_trade
from execution.simulator import simulate_trade



class BacktestEngine:


    def __init__(
            self,
            starting_balance=50
    ):


        self.balance = starting_balance

        self.starting_balance = starting_balance


        self.trades = []

        self.equity_curve = [

            starting_balance

        ]


        self.total_trades = 0

        self.wins = 0

        self.losses = 0



    def execute_trade(
            self,
            signal,
            candle
    ):


        """
        Executes one simulated trade
        """


        if signal["signal"] == "NO_TRADE":

            return None



        risk = approve_trade(
            signal
        )


        if not risk["approved"]:

            return None



        result = simulate_trade(

            signal,

            candle

        )


        if result is None:

            return None



        profit = result["profit"]



        self.balance += profit



        self.total_trades += 1



        if profit > 0:

            self.wins += 1

        else:

            self.losses += 1




        trade_record = {


            "type":

            signal["signal"],


            "profit":

            profit,


            "entry":

            result.get(
                "entry",
                candle["close"]
            ),


            "exit":

            result.get(
                "exit",
                candle["close"]
            ),


            "confidence":

            signal.get(
                "confidence",
                0
            )

        }



        self.trades.append(

            trade_record

        )



        self.equity_curve.append(

            self.balance

        )



        return result




    def statistics(self):


        return {


            "Starting Balance":

            self.starting_balance,


            "Ending Balance":

            round(
                self.balance,
                2
            ),


            "Net Profit":

            round(
                self.balance -
                self.starting_balance,
                2
            ),


            "Trades":

            self.total_trades,


            "Wins":

            self.wins,


            "Losses":

            self.losses

        }