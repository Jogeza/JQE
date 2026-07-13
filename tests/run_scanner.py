import sys
import os

sys.path.append(
    os.path.dirname(
        os.path.dirname(
            os.path.abspath(__file__)
        )
    )
)

from core.market_scanner import MarketScanner



print("""
=============================
 JQE AUTONOMOUS MARKET SCANNER
=============================
""")


scanner = MarketScanner()


markets = scanner.autonomous_scan()



for market in markets:


    print("\nSYMBOL:", market["symbol"])

    print("--------------------------")

    print("TREND:", market["trend"])

    print("VOLATILITY:", market["volatility"])

    print("LIQUIDITY:", market["liquidity"])

    print("SCORE:", market["market_score"])

    print("TRADE READY:", market["trade_ready"])