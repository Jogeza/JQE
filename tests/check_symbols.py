import MetaTrader5 as mt5


mt5.initialize()


symbols = mt5.symbols_get()


for symbol in symbols:

    name = symbol.name

    if (
        "US30" in name.upper()
        or
        "DOW" in name.upper()
        or
        "DJ" in name.upper()
    ):
        print(name)


mt5.shutdown()