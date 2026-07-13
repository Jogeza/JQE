class PositionSizing:



    def calculate_lot(
        self,
        risk_amount,
        stop_distance,
        pip_value=1
    ):


        if stop_distance <= 0:

            return 0



        lot = (
            risk_amount /
            (
                stop_distance *
                pip_value
            )
        )


        return round(
            lot,
            2
        )