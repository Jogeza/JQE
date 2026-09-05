"""Shared realized-balance drawdown convention used by results and replay."""


def balance_drawdown(balance: float, peak: float) -> tuple[float, float, float]:
    peak = max(peak, balance)
    amount = peak - balance
    return peak, amount, amount / peak * 100.0 if peak else 0.0
