"""
JQE Institutional Risk Manager

Handles:
- Risk percentage
- Position sizing
- Stop loss calculation
- Take profit calculation
- Account protection
"""


from core.logger import logger



def calculate_risk(
        balance,
        risk_percent=1
):

    """
    Calculate maximum money allowed to lose.
    """


    risk_amount = (
        balance *
        risk_percent /
        100
    )


    return round(
        risk_amount,
        2
    )




def calculate_position_size(
        balance,
        stop_loss_distance,
        risk_percent=1,
        tick_value=1
):

    """
    Dynamic lot calculation.

    Prevents fixed lot trading.
    """


    risk_money = calculate_risk(

        balance,

        risk_percent

    )



    if stop_loss_distance <= 0:

        return 0



    lot_size = (

        risk_money /

        (
            stop_loss_distance *
            tick_value
        )

    )



    # Broker safety limits

    if lot_size < 0.01:

        lot_size = 0.01



    if lot_size > 100:

        lot_size = 100



    return round(
        lot_size,
        2
    )




def calculate_stop_loss(
        entry_price,
        atr,
        direction
):

    """
    ATR based stop loss.
    """


    multiplier = 2



    distance = (
        atr *
        multiplier
    )



    if direction == "BUY":

        stop_loss = (
            entry_price -
            distance
        )



    elif direction == "SELL":

        stop_loss = (
            entry_price +
            distance
        )



    else:

        stop_loss = None



    return round(
        stop_loss,
        2
    )




def calculate_take_profit(
        entry_price,
        atr,
        direction
):

    """
    Risk reward target.
    1:2 reward ratio.
    """


    multiplier = 4



    distance = (
        atr *
        multiplier
    )



    if direction == "BUY":

        take_profit = (
            entry_price +
            distance
        )



    elif direction == "SELL":

        take_profit = (
            entry_price -
            distance
        )



    else:

        take_profit = None



    return round(
        take_profit,
        2
    )