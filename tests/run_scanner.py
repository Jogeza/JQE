"""
JQE Autonomous Market Scanner Runner
Version: 0.1.3

Displays:
- Trend
- Volatility
- Momentum
- Liquidity
- ATR
- RSI
- Market Score
"""



from core.market_scanner import MarketScanner





def main():



    print()

    print("=============================")

    print(" JQE AUTONOMOUS MARKET SCANNER ")

    print("=============================")

    print()



    scanner = MarketScanner()



    markets = scanner.autonomous_scan()



    for market in markets:



        print()

        print(
            f"SYMBOL: {market['symbol']}"
        )

        print(
            "--------------------------"
        )



        print(
            f"TREND: {market.get('trend','UNKNOWN')}"
        )


        print(
            f"VOLATILITY: {market.get('volatility','UNKNOWN')}"
        )


        print(
            f"MOMENTUM: {market.get('momentum','UNKNOWN')}"
        )


        print(
            f"LIQUIDITY: {market.get('liquidity','UNKNOWN')}"
        )



        print(
            f"PRICE: {market.get('price','N/A')}"
        )


        print(
            f"ATR: {market.get('atr','N/A')}"
        )


        print(
            f"RSI: {market.get('rsi','N/A')}"
        )


        print(
            f"SCORE: {market.get('market_score',0)}"
        )


        print(
            f"TRADE READY: {market.get('trade_ready',False)}"
        )



        print()





if __name__ == "__main__":


    main()