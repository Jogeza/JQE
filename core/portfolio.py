class Portfolio:


    def __init__(self):

        self.positions = []



    def add(
        self,
        position
    ):

        self.positions.append(
            position
        )



    def get_positions(
        self
    ):

        return self.positions