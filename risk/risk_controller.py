"""
JQE Risk Controller

Controls whether a trade is allowed.

Responsibilities:
- Validate signal quality
- Calculate risk
- Calculate position size
- Generate SL / TP
"""


from risk.risk_manager import (
    calculate_position_size,
    calculate_stop_loss,
    calculate_take_profit
)

from core.logger import logger




def evaluate_trade(
        signal_data,
        df,
        balance,
        risk_percent=1
):

    """
    Final trade permission system.
    """



    signal = signal_data["signal"]

    confidence = signal_data["confidence"]



    latest = df.iloc[-1]


    entry_price = latest["close"]

    atr = latest["ATR"]



    # ======================
    # BLOCK NO TRADE SIGNALS
    # ======================


    if signal == "NO_TRADE":


        return {

            "approved": False,

            "reason": "No trade signal"

        }



    # ======================
    # CONFIDENCE FILTER
    # ======================


    minimum_confidence = 70



    if confidence < minimum_confidence:


        return {

            "approved": False,

            "reason":
            "Confidence below minimum"

        }



    # ======================
    # STOP LOSS DISTANCE
    # ======================


    stop_distance = atr * 2



    # ======================
    # POSITION SIZE
    # ======================


    lot = calculate_position_size(

        balance,

        stop_distance,

        risk_percent

    )



    # ======================
    # SL / TP
    # ======================


    stop_loss = calculate_stop_loss(

        entry_price,

        atr,

        signal

    )



    take_profit = calculate_take_profit(

        entry_price,

        atr,

        signal

    )



    trade_plan = {


        "approved": True,


        "signal": signal,


        "confidence": confidence,


        "entry": round(
            entry_price,
            2
        ),


        "lot": lot,


        "stop_loss": stop_loss,


        "take_profit": take_profit,


        "risk_percent": risk_percent


    }



    logger.info(

        f"Trade approved: {trade_plan}"

    )



    return trade_plan