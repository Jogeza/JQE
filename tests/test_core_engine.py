from core.engine import JQEEngine



engine = JQEEngine()



engine.start()



markets = engine.scan_markets(

    [
        "GOLD",
        "BTCUSD",
        "DOW30",
        "EURUSD"
    ]

)



print("\nMARKET SCANNER")
print(markets)



signal = {

    "action":"BUY"

}



score = {

    "quality":"HIGH",

    "confidence":85

}



risk = {

    "risk_percent":1.5

}



decision = engine.evaluate_trade(

    signal,

    score,

    risk

)



print("\nTRADE DECISION")
print(decision)