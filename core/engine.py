from core.market_scanner import MarketScanner
from core.portfolio import Portfolio
from core.decision_pipeline import DecisionPipeline


class JQEEngine:


    def __init__(self):

        self.portfolio = Portfolio()

        self.pipeline = DecisionPipeline()



    def start(self):

        print("==========================")
        print(" JQE INSTITUTIONAL CORE ")
        print(" ENGINE ONLINE ")
        print("==========================")



    def scan_markets(
        self,
        symbols
    ):

        scanner = MarketScanner(
            symbols
        )

        return scanner.scan()



    def evaluate_trade(
        self,
        signal,
        score,
        risk
    ):

        decision = self.pipeline.decide(
            signal,
            score,
            risk
        )

        return decision