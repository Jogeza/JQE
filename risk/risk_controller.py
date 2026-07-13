"""
JQE Institutional Risk Controller
Version 0.1.0

Responsibilities:

- Protect account capital
- Filter weak signals
- Control risk exposure
- Calculate position size
- Prevent overtrading
"""


# ==========================
# INSTITUTIONAL PARAMETERS
# ==========================


MIN_CONFIDENCE = 75

MAX_RISK_PERCENT = 0.5

MIN_ATR = 1.0

MAX_SPREAD = 30





# ==========================
# MAIN RISK ENGINE
# ==========================


def approve_trade(

        signal,

        market_data

):


    decision = {


        "approved": False,

        "reason": "",

        "risk_percent": 0,

        "lot_size": 0

    }




    # --------------------------
    # Check signal existence
    # --------------------------


    if signal is None:


        decision["reason"] = (

            "Missing signal"

        )


        return decision





    direction = signal.get(

        "signal"

    )



    if direction not in [

        "BUY",

        "SELL"

    ]:


        decision["reason"] = (

            "No trade signal"

        )


        return decision





    # --------------------------
    # Confidence filter
    # --------------------------


    confidence = signal.get(

        "confidence",

        0

    )



    if confidence < MIN_CONFIDENCE:


        decision["reason"] = (

            "Confidence too low"

        )


        return decision





    # --------------------------
    # Market validation
    # --------------------------


    try:


        candle = market_data.iloc[-1]


    except:


        decision["reason"] = (

            "Invalid market data"

        )


        return decision






    # ATR filter


    atr = candle.get(

        "ATR",

        0

    )



    if atr < MIN_ATR:


        decision["reason"] = (

            "Low volatility"

        )


        return decision





    # Spread protection


    spread = candle.get(

        "spread",

        0

    )



    if spread > MAX_SPREAD:


        decision["reason"] = (

            "Spread too high"

        )


        return decision





    # --------------------------
    # APPROVE TRADE
    # --------------------------


    decision["approved"] = True


    decision["reason"] = (

        "Institutional risk passed"

    )



    decision["risk_percent"] = (

        MAX_RISK_PERCENT

    )



    decision["lot_size"] = calculate_position_size(

        balance=50,

        risk_percent=MAX_RISK_PERCENT,

        stop_loss=atr

    )



    return decision







# ==========================
# POSITION SIZE ENGINE
# ==========================


def calculate_position_size(

        balance,

        risk_percent,

        stop_loss

):


    if stop_loss <= 0:


        return 0.01





    risk_amount = (

        balance *

        risk_percent /

        100

    )




    lot = (

        risk_amount /

        (

            stop_loss *

            10

        )

    )




    # MT5 minimum lot protection


    if lot < 0.01:


        lot = 0.01




    return round(

        lot,

        2

    )