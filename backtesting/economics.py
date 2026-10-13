"""Frozen, offline-only CFD economics. No broker sessions or order paths."""
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP
import math

from backtesting.models import _sha256
from broker.types import ExecutionQuantity, ExecutionQuantityUnit
from broker.weltrade_symbols import require_weltrade_synthetic
from data.dataset import candle_content_hash


def cash(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal(".01"), rounding=ROUND_HALF_UP))


@dataclass(frozen=True, slots=True)
class FrozenCFDContract:
    symbol: str
    account_currency: str
    tick_size: float
    tick_value_profit: float
    tick_value_loss: float
    contract_size: float
    volume_min: float
    volume_step: float
    volume_max: float
    minimum_stop_price: float
    margin_ratio_upper: float
    swap_long_percent: float
    swap_short_percent: float
    triple_swap_weekday_mt5: int
    server_offset_seconds: int

    def __post_init__(self):
        if require_weltrade_synthetic(self.symbol) != self.symbol or self.account_currency != "USD":
            raise ValueError("Frozen model requires exact native Weltrade symbol and USD economics")
        positive = (self.tick_size, self.tick_value_profit, self.tick_value_loss, self.contract_size,
                    self.volume_min, self.volume_step, self.volume_max, self.margin_ratio_upper)
        if not all(math.isfinite(x) and x > 0 for x in positive):
            raise ValueError("Frozen contract economics must be positive and finite")
        if self.volume_max < self.volume_min or self.minimum_stop_price < 0 or not math.isfinite(self.minimum_stop_price):
            raise ValueError("Invalid frozen quantity/stop limits")
        if not all(math.isfinite(x) for x in (self.swap_long_percent, self.swap_short_percent)):
            raise ValueError("Invalid frozen swap rates")
        if self.triple_swap_weekday_mt5 not in range(7) or abs(self.server_offset_seconds) > 14 * 3600:
            raise ValueError("Invalid rollover calendar")

    def pnl(self, side: str, lots: float, entry: float, exit: float) -> float:
        if side not in ("BUY", "SELL") or not all(math.isfinite(x) and x > 0 for x in (lots,entry,exit)):
            raise ValueError("Invalid offline P/L inputs")
        move = (exit - entry) * (1 if side == "BUY" else -1)
        value = self.tick_value_profit if move >= 0 else self.tick_value_loss
        return cash(move / self.tick_size * value * lots)

    def margin(self, lots: float, price: float) -> float:
        return math.ceil(price * lots * self.margin_ratio_upper * 100 - 1e-9) / 100

    def price(self, value: float, *, up: bool) -> float:
        # Remove sub-billionth-tick floating arithmetic residue before rounding
        # outward; 1000 + .2 + .1 must not become an extra adverse whole tick.
        ratio = (Decimal(str(value)) / Decimal(str(self.tick_size))).quantize(Decimal(".00000001"),rounding=ROUND_HALF_UP)
        ticks = ratio.to_integral_value(rounding=ROUND_CEILING if up else ROUND_FLOOR)
        return float(ticks * Decimal(str(self.tick_size)))

    def carry(self, side: str, lots: float, previous: datetime, current: datetime, price: float) -> float:
        if previous.tzinfo is None or current.tzinfo is None or current < previous:
            raise ValueError("Rollover timestamps must be aware and ordered")
        shift = timedelta(seconds=self.server_offset_seconds)
        day = (previous + shift).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        rate = self.swap_long_percent if side == "BUY" else self.swap_short_percent
        charge = 0.0
        while day - shift <= current:
            ending_day = day - timedelta(days=1)
            if ending_day.weekday() < 5:
                weight = 3 if (ending_day.weekday()+1) % 7 == self.triple_swap_weekday_mt5 else 1
                charge += cash(-price * self.contract_size * lots * rate / 100 / 360 * weight)
            day += timedelta(days=1)
        return charge


@dataclass(frozen=True, slots=True)
class FrozenCostPolicy:
    commission_per_lot_per_side: float
    spread_multiplier: float = 1.0
    slippage_atr_fraction_per_fill: float = .05
    commission_status: str = "ASSUMED_NOT_VERIFIED"
    financing_status: str = "CURRENT_RATES_ENDING_SERVER_DAY_CALENDAR_ASSUMED"

    def __post_init__(self):
        if not all(math.isfinite(x) and x >= 0 for x in (
            self.commission_per_lot_per_side, self.spread_multiplier, self.slippage_atr_fraction_per_fill)):
            raise ValueError("Frozen costs must be nonnegative and finite")


@dataclass(frozen=True, slots=True)
class FrozenMarketModel:
    contract: FrozenCFDContract
    policy: FrozenCostPolicy
    timestamps: tuple[datetime, ...]
    spread_prices: tuple[float, ...]
    dataset_content_hash: str
    evidence_hashes: tuple[tuple[str, str], ...]

    def __post_init__(self):
        if not self.timestamps or len(self.timestamps) != len(self.spread_prices):
            raise ValueError("Complete timestamp-bound spreads required")
        if any(t.tzinfo is None for t in self.timestamps) or any(b <= a for a,b in zip(self.timestamps,self.timestamps[1:])):
            raise ValueError("Frozen spread times must be aware, unique and increasing")
        if not all(math.isfinite(x) and x >= 0 for x in self.spread_prices):
            raise ValueError("Invalid frozen spreads")

    def validate_dataset(self, candles, symbol: str, provider: str):
        if provider != "weltrade" or symbol != self.contract.symbol:
            raise ValueError("Frozen model provider/symbol mismatch")
        if tuple(c.time for c in candles) != self.timestamps or candle_content_hash(candles) != self.dataset_content_hash:
            raise ValueError("Frozen costs do not bind to this exact candle sequence")

    def identity(self) -> dict:
        return {"model_version": "frozen-weltrade-cfd-v2", "contract": asdict(self.contract),
            "policy": asdict(self.policy), "spread_input_hash": _sha256({"times": self.timestamps, "prices": self.spread_prices}),
            "dataset_content_hash": self.dataset_content_hash, "evidence_hashes": dict(self.evidence_hashes),
            "claim_scope": "CONDITIONAL_MODELLED_USD_NOT_VERIFIED_HISTORICAL_FILLS_OR_TARIFF",
            "fill_policy": "bid OHLC; prior closed-bar spread; adverse slippage both fills; stop gap at adverse open; stop first",
            "risk_policy": "lot-step floor; cash-risk inclusive of round-trip commission, exit slippage and worst one-rollover reserve; conservative snapshot margin",
            "signal_spread_policy": "preserve canonical v2 unknown-spread fallback; sidecar used only for modeled fills",
            "rollover_policy": "ending server day Mon-Fri; captured triple weekday; prior closed bid proxy; fixed captured clock offset"}

    def spread(self, index: int) -> float:
        if index <= 0:
            raise ValueError("A previous closed spread observation is required")
        return self.spread_prices[index - 1] * self.policy.spread_multiplier

    def exit_price(self, side: str, quote_price: float, slippage: float) -> float:
        """Round the adverse executable quote identically for risk, marks and fills."""
        if side not in ("BUY", "SELL") or not math.isfinite(slippage) or slippage < 0:
            raise ValueError("Invalid exit side/slippage")
        return self.contract.price(quote_price-slippage if side == "BUY" else quote_price+slippage,
                                   up=side == "SELL")

    def quantity(self, balance: float, risk_percent: float, entry: float, stop: float,
                 exit_slippage: float, side: str) -> ExecutionQuantity:
        c, p = self.contract, self.policy
        worst_stop = self.exit_price(side, stop, exit_slippage)
        value_loss = c.tick_value_loss / c.tick_size
        rate = c.swap_long_percent if side == "BUY" else c.swap_short_percent
        carry_reserve = max(0, -rate) * entry * c.contract_size / 100 / 360 * 3
        per_lot_risk = abs(entry-worst_stop) * value_loss + 2*p.commission_per_lot_per_side + carry_reserve
        budget = balance * risk_percent / 100
        if not all(math.isfinite(x) and x > 0 for x in (per_lot_risk, budget, entry)):
            raise ValueError("Invalid cash risk or capital")
        raw = min(budget / per_lot_risk, balance / (entry*c.margin_ratio_upper + p.commission_per_lot_per_side), c.volume_max)
        units = (Decimal(str(raw))/Decimal(str(c.volume_step))).to_integral_value(rounding=ROUND_FLOOR)
        lots = float(units * Decimal(str(c.volume_step)))
        # Include cent rounding of commissions and margin in the final check.
        while lots >= c.volume_min:
            estimated_risk = abs(c.pnl(side,lots,entry,worst_stop)) + 2*cash(p.commission_per_lot_per_side*lots) + cash(carry_reserve*lots)
            if estimated_risk <= budget + 1e-9 and c.margin(lots,entry) + cash(p.commission_per_lot_per_side*lots) <= balance:
                return ExecutionQuantity(value=lots, unit=ExecutionQuantityUnit.MT5_LOTS)
            lots = float(Decimal(str(lots)) - Decimal(str(c.volume_step)))
        raise ValueError("Minimum lot cannot satisfy frozen cash-risk/margin limits")


def contract_from_evidence(symbol: str, economics: dict, terms: dict, *, server_offset: int) -> FrozenCFDContract:
    if terms["symbol"] != symbol or terms["trade_calc_mode"] != 2 or terms["chart_mode"] != 0 or terms["swap_mode"] != 5:
        raise ValueError("Only captured bid-chart CFD / interest-current swap conventions supported")
    if terms["currency_profit"] != "USD" or terms["currency_margin"] != "USD" or economics["account_currency"] != "USD":
        raise ValueError("Currency conversion is not verified for this contract")
    for field in ("point", "volume_min", "volume_step", "volume_max", "trade_contract_size", "trade_tick_size",
                  "trade_tick_value_profit", "trade_tick_value_loss", "trade_stops_level", "swap_mode", "swap_long", "swap_short"):
        if terms[field] != economics[field]:
            raise ValueError(f"Contract snapshots disagree: {field}")
    lower, upper = 0.0, math.inf
    if len(terms["margin_probes"]) < 4:
        raise ValueError("Both directions and multiple lot sizes required for margin evidence")
    for probe in terms["margin_probes"]:
        margin = probe["margin"]
        if margin is None or not math.isfinite(margin) or margin <= 0:
            raise ValueError("Unverifiable margin probe")
        nominal = probe["price"] * probe["lots"]
        lower, upper = max(lower,(margin-.005)/nominal), min(upper,(margin+.005)/nominal)
    if lower > upper or not math.isfinite(upper):
        raise ValueError("Margin observations do not support a common conservative rate")
    c = FrozenCFDContract(symbol, "USD", terms["trade_tick_size"], terms["trade_tick_value_profit"],
        terms["trade_tick_value_loss"], terms["trade_contract_size"], terms["volume_min"], terms["volume_step"],
        terms["volume_max"], terms["trade_stops_level"]*terms["point"], upper, terms["swap_long"], terms["swap_short"],
        int(terms["swap_rollover3days"]), server_offset)
    probes = economics["profit_probes"]
    if len(probes) != 8 or {p["side"] for p in probes} != {"BUY", "SELL"}:
        raise ValueError("Eight two-sided frozen P/L probes required")
    if any(abs(c.pnl(p["side"],p["lots"],p["entry"],p["exit"]) - p["pnl"]) > .005001 for p in probes):
        raise ValueError("Offline P/L model fails broker probe equivalence")
    return c
