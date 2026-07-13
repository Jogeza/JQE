class PositionManager:



    def __init__(self):

        self.positions = []



    def open_position(
        self,
        order
    ):


        position = {


            "symbol":
                order["symbol"],


            "direction":
                order["type"],


            "lot":
                order["lot"],


            "entry":
                order["entry"],


            "stop_loss":
                order["stop_loss"],


            "take_profit":
                order["take_profit"],


            "status":
                "OPEN"

        }


        self.positions.append(
            position
        )


        return position




    def get_positions(
        self
    ):

        return self.positions