from data.market_loader import MarketLoader
from data.historical_data import HistoricalData
from data.validator import DataValidator
from data.symbol_manager import SymbolManager



class DataManager:


    def __init__(self):

        self.database = HistoricalData()

        self.symbol_manager = SymbolManager()



    def collect(
        self,
        symbol,
        timeframe="M15",
        candles=1000
    ):


        broker_symbol = self.symbol_manager.get_broker_symbol(
            symbol
        )


        loader = MarketLoader(
            broker_symbol
        )


        loader.connect()


        data = loader.get_candles(
            count=candles
        )


        DataValidator.check_missing(data)

        DataValidator.check_duplicates(data)


        self.database.save(
            data,
            symbol,
            timeframe
        )


        return data