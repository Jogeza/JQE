from core.market_scanner import MarketScanner



def test_autonomous_scanner():


    scanner = MarketScanner()


    markets = scanner.autonomous_scan()


    assert len(markets) == 4


    assert markets[0]["symbol"] == "GOLD"


    assert "market_score" in markets[0]