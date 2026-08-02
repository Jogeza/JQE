from core.market_scanner import MarketScanner


def test_live_market_scan():

    scanner = MarketScanner(
        symbols=[
            "XAUUSD",
            "BTCUSD",
            "EURUSD"
        ]
    )

    results = scanner.scan()

    print("\n\n===== JQE LIVE MARKET SCAN =====")

    for result in results:
        print("\n----------------------")
        print(result)

    assert results is not None
    assert len(results) > 0