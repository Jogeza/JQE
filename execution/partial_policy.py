"""Pure fixed demo partial-exit math; never enlarges authorized risk."""
from decimal import Decimal, ROUND_FLOOR
import math


def split_lots(authorized_lots, minimum, step):
    if not all(math.isfinite(x) and x>0 for x in (authorized_lots,minimum,step)):
        raise ValueError('Finite broker quantity rules required')
    quantum=Decimal(str(step));minimum_d=Decimal(str(minimum))
    units=(Decimal(str(authorized_lots))/(2*quantum)).to_integral_value(rounding=ROUND_FLOOR)
    portion=units*quantum
    if portion<minimum_d:
        raise ValueError('Risk budget cannot fund two minimum-volume portions')
    return float(2*portion),float(portion)


def levels(side,entry,original_stop):
    if side not in ('BUY','SELL') or not all(math.isfinite(x) and x>0 for x in (entry,original_stop)):
        raise ValueError('Verified original entry/stop required')
    sign=1 if side=='BUY' else -1
    risk=sign*(entry-original_stop)
    if risk<=0:raise ValueError('Original stop must protect entry')
    return entry+sign*1.5*risk,entry+sign*.5*risk


def ready(side,quote,entry,original_stop,minimum_distance):
    trigger,stop=levels(side,entry,original_stop)
    if not math.isfinite(quote) or quote<=0 or not math.isfinite(minimum_distance) or minimum_distance<0:
        return False
    sign=1 if side=='BUY' else -1
    return sign*(quote-trigger)>=0 and sign*(quote-stop)>minimum_distance
