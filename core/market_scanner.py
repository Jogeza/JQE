class MarketScanner:


    def __init__(
        self,
        symbols
    ):

        self.symbols = symbols



    def scan(self):

        markets = []


        for symbol in self.symbols:

            markets.append(

                {
                    "symbol": symbol,
                    "status": "READY"
                }

            )


        return markets