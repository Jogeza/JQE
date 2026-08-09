import json


class SymbolManager:


    def __init__(
        self,
        file="data/symbols.json"
    ):

        with open(file, "r") as f:
            self.symbols = json.load(f)



    def get_broker_symbol(
        self,
        jqe_symbol
    ):

        if jqe_symbol not in self.symbols:
            raise Exception(
                f"Unknown symbol {jqe_symbol}"
            )

        return self.symbols[jqe_symbol]
