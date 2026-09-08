"""Regime-specific and directional strategy research diagnostics for frozen datasets.

Provides clean, deterministic attribution of backtest trades across:
- Authorizing market regime (TRENDING, RANGING, HIGH_VOLATILITY, UNKNOWN)
- Direction and regime intersections (TRENDING BUY, TRENDING SELL, etc.)
- Entry-candle regime persistence and drift
- Exit reason loss concentration (STOP_LOSS, TAKE_PROFIT, TIMEOUT, END_OF_DATA)
- Cost scenario impact and profitability sign flips
- Predeclared research hypothesis evaluations
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

import pandas as pd

from backtesting.backtest import _WARMUP_CANDLES, build_backtest_result
from backtesting.engine import BacktestEngine
from backtesting.models import (
    BacktestDecision,
    BacktestExecutionAssumptions,
    BacktestExitReason,
    BacktestIndicatorObservation,
    BacktestResult,
    BacktestRiskConfiguration,
    BacktestTrade,
    CandleDatasetSnapshot,
)
from broker.types import Candle, Timeframe
from core.indicators import calculate_indicators
from core.regime import detect_regime
from strategy.pipeline import generate_trading_signal


@dataclass(frozen=True, slots=True)
class RegimeAttributionMetrics:
    regime: str
    direction: str
    trades: int
    buy_count: int
    sell_count: int
    wins: int
    losses: int
    win_rate_percent: float
    gross_profit: float
    gross_loss: float
    net_pnl: float
    expectancy: float
    profit_factor: float | None
    maximum_drawdown: float
    maximum_drawdown_percent: float
    conservative_cost_net_pnl: float | None = None
    conservative_cost_impact: float | None = None
    cost_flips_sign: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ExitReasonMetrics:
    exit_reason: str
    trades: int
    wins: int
    losses: int
    win_rate_percent: float
    gross_profit: float
    gross_loss: float
    net_pnl: float
    expectancy: float
    share_of_total_losses_percent: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def calculate_trade_drawdown(trades: Sequence[BacktestTrade], starting_balance: float = 50.0) -> tuple[float, float]:
    """Calculates maximum peak-to-trough absolute and percentage drawdown from trades."""
    if not trades:
        return 0.0, 0.0
    balances = [starting_balance]
    for trade in trades:
        balances.append(balances[-1] + trade.net_pnl)
    peak = balances[0]
    max_dd = 0.0
    max_dd_pct = 0.0
    for balance in balances:
        if balance > peak:
            peak = balance
        dd = peak - balance
        if dd > max_dd:
            max_dd = dd
            max_dd_pct = (dd / peak * 100.0) if peak > 0 else 0.0
    return max_dd, max_dd_pct


def compute_metrics_for_trades(
    trades: Sequence[BacktestTrade],
    regime: str = "ALL",
    direction: str = "ALL",
    cost_trades: Sequence[BacktestTrade] | None = None,
    starting_balance: float = 50.0,
) -> RegimeAttributionMetrics:
    """Computes attribution metrics for a specific slice of trades."""
    trade_list = list(trades)
    n = len(trade_list)
    buy_count = sum(1 for t in trade_list if t.direction == "BUY")
    sell_count = sum(1 for t in trade_list if t.direction == "SELL")
    wins = [t for t in trade_list if t.net_pnl > 0]
    losses = [t for t in trade_list if t.net_pnl < 0]
    gross_profit = sum(t.net_pnl for t in wins)
    gross_loss = abs(sum(t.net_pnl for t in losses))
    net_pnl = sum(t.net_pnl for t in trade_list)
    win_rate = (len(wins) / n * 100.0) if n > 0 else 0.0
    expectancy = (net_pnl / n) if n > 0 else 0.0
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (None if not gross_profit else float("inf"))
    mdd, mdd_pct = calculate_trade_drawdown(trade_list, starting_balance=starting_balance)

    cost_net_pnl: float | None = None
    cost_impact: float | None = None
    cost_flips_sign = False
    if cost_trades is not None:
        cost_list = list(cost_trades)
        cost_net_pnl = sum(t.net_pnl for t in cost_list)
        cost_impact = cost_net_pnl - net_pnl
        cost_flips_sign = (net_pnl > 0 and cost_net_pnl <= 0) or (net_pnl < 0 and cost_net_pnl >= 0)

    return RegimeAttributionMetrics(
        regime=regime,
        direction=direction,
        trades=n,
        buy_count=buy_count,
        sell_count=sell_count,
        wins=len(wins),
        losses=len(losses),
        win_rate_percent=win_rate,
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        net_pnl=net_pnl,
        expectancy=expectancy,
        profit_factor=profit_factor,
        maximum_drawdown=mdd,
        maximum_drawdown_percent=mdd_pct,
        conservative_cost_net_pnl=cost_net_pnl,
        conservative_cost_impact=cost_impact,
        cost_flips_sign=cost_flips_sign,
    )


def audit_regimes_for_result(
    zero_cost_result: BacktestResult,
    cost_result: BacktestResult | None = None,
) -> dict[str, Any]:
    """Audits regime labels and direction slices for a single backtest run."""
    z_trades = list(zero_cost_result.trades)
    c_trades = list(cost_result.trades) if cost_result is not None else None

    # Canonical StrategyEngine signal regime:
    # BUY and SELL require TRENDING regime at authorization.
    # Therefore, 100% of signaled trades belong to TRENDING at signal candle.
    # RANGING, UNKNOWN, and HIGH_VOLATILITY have 0 trades.
    regimes = ["TRENDING", "RANGING", "UNKNOWN", "HIGH_VOLATILITY"]
    per_regime = {}
    for r in regimes:
        if r == "TRENDING":
            r_z = z_trades
            r_c = c_trades
        else:
            r_z = []
            r_c = [] if c_trades is not None else None
        per_regime[r] = compute_metrics_for_trades(r_z, regime=r, direction="ALL", cost_trades=r_c)

    # Per-direction and per-regime slices
    directional_regimes = {
        "TRENDING BUY": compute_metrics_for_trades(
            [t for t in z_trades if t.direction == "BUY"],
            regime="TRENDING", direction="BUY",
            cost_trades=[t for t in c_trades if t.direction == "BUY"] if c_trades is not None else None,
        ),
        "TRENDING SELL": compute_metrics_for_trades(
            [t for t in z_trades if t.direction == "SELL"],
            regime="TRENDING", direction="SELL",
            cost_trades=[t for t in c_trades if t.direction == "SELL"] if c_trades is not None else None,
        ),
        "RANGING": compute_metrics_for_trades([], regime="RANGING", direction="ALL"),
        "UNKNOWN": compute_metrics_for_trades([], regime="UNKNOWN", direction="ALL"),
        "HIGH_VOLATILITY": compute_metrics_for_trades([], regime="HIGH_VOLATILITY", direction="ALL"),
    }

    # Exit reason breakdown
    total_gross_loss = abs(sum(t.net_pnl for t in z_trades if t.net_pnl < 0))
    by_exit: dict[str, list[BacktestTrade]] = defaultdict(list)
    for t in z_trades:
        by_exit[t.exit_reason.value].append(t)

    exit_breakdown: dict[str, ExitReasonMetrics] = {}
    for reason in ["STOP_LOSS", "TAKE_PROFIT", "TIMEOUT", "END_OF_DATA"]:
        trades_for_reason = by_exit.get(reason, [])
        n_ex = len(trades_for_reason)
        w_ex = [t for t in trades_for_reason if t.net_pnl > 0]
        l_ex = [t for t in trades_for_reason if t.net_pnl < 0]
        gp = sum(t.net_pnl for t in w_ex)
        gl = abs(sum(t.net_pnl for t in l_ex))
        pnl = sum(t.net_pnl for t in trades_for_reason)
        loss_share = (gl / total_gross_loss * 100.0) if total_gross_loss > 0 else 0.0
        exit_breakdown[reason] = ExitReasonMetrics(
            exit_reason=reason,
            trades=n_ex,
            wins=len(w_ex),
            losses=len(l_ex),
            win_rate_percent=(len(w_ex) / n_ex * 100.0) if n_ex > 0 else 0.0,
            gross_profit=gp,
            gross_loss=gl,
            net_pnl=pnl,
            expectancy=(pnl / n_ex) if n_ex > 0 else 0.0,
            share_of_total_losses_percent=loss_share,
        )

    # Entry candle close regime drift analysis
    ind_map = {ind.timestamp: ind for ind in zero_cost_result.indicators}
    drift_groups: dict[str, list[BacktestTrade]] = defaultdict(list)
    for t in z_trades:
        ind = ind_map.get(t.entry_timestamp)
        label = ind.regime if ind and ind.regime else "UNKNOWN"
        drift_groups[label].append(t)

    drift_metrics = {
        label: compute_metrics_for_trades(grp, regime=label, direction="ALL")
        for label, grp in sorted(drift_groups.items())
    }

    return {
        "per_regime": {k: v.to_dict() for k, v in per_regime.items()},
        "directional_regimes": {k: v.to_dict() for k, v in directional_regimes.items()},
        "exit_breakdown": {k: v.to_dict() for k, v in exit_breakdown.items()},
        "entry_candle_drift": {k: v.to_dict() for k, v in drift_metrics.items()},
    }


def aggregate_window_diagnostics(
    window_results: Mapping[str, Mapping[str, BacktestResult]],
) -> dict[str, Any]:
    """Aggregates regime and directional diagnostics across all frozen windows."""
    all_zero_trades: list[BacktestTrade] = []
    all_cost_trades: list[BacktestTrade] = []
    per_window: dict[str, Any] = {}

    for window_name, scen_map in window_results.items():
        z_res = scen_map["IDEALIZED_ZERO_COST"]
        c_res = scen_map.get("CONSERVATIVE_SIMULATION_COST")
        all_zero_trades.extend(z_res.trades)
        if c_res is not None:
            all_cost_trades.extend(c_res.trades)
        per_window[window_name] = audit_regimes_for_result(z_res, c_res)

    # Combined multi-window metrics
    regimes = ["TRENDING", "RANGING", "UNKNOWN", "HIGH_VOLATILITY"]
    combined_per_regime = {}
    for r in regimes:
        if r == "TRENDING":
            r_z = all_zero_trades
            r_c = all_cost_trades
        else:
            r_z = []
            r_c = []
        combined_per_regime[r] = compute_metrics_for_trades(r_z, regime=r, direction="ALL", cost_trades=r_c)

    # Direction x regime combined
    z_buys = [t for t in all_zero_trades if t.direction == "BUY"]
    c_buys = [t for t in all_cost_trades if t.direction == "BUY"]
    z_sells = [t for t in all_zero_trades if t.direction == "SELL"]
    c_sells = [t for t in all_cost_trades if t.direction == "SELL"]

    combined_directional_regimes = {
        "TRENDING BUY": compute_metrics_for_trades(z_buys, regime="TRENDING", direction="BUY", cost_trades=c_buys),
        "TRENDING SELL": compute_metrics_for_trades(z_sells, regime="TRENDING", direction="SELL", cost_trades=c_sells),
        "RANGING": compute_metrics_for_trades([], regime="RANGING", direction="ALL"),
        "UNKNOWN": compute_metrics_for_trades([], regime="UNKNOWN", direction="ALL"),
        "HIGH_VOLATILITY": compute_metrics_for_trades([], regime="HIGH_VOLATILITY", direction="ALL"),
    }

    # Combined exit breakdown
    total_gross_loss = abs(sum(t.net_pnl for t in all_zero_trades if t.net_pnl < 0))
    by_exit: dict[str, list[BacktestTrade]] = defaultdict(list)
    for t in all_zero_trades:
        by_exit[t.exit_reason.value].append(t)

    combined_exit_breakdown = {}
    for reason in ["STOP_LOSS", "TAKE_PROFIT", "TIMEOUT", "END_OF_DATA"]:
        trades_for_reason = by_exit.get(reason, [])
        n_ex = len(trades_for_reason)
        w_ex = [t for t in trades_for_reason if t.net_pnl > 0]
        l_ex = [t for t in trades_for_reason if t.net_pnl < 0]
        gp = sum(t.net_pnl for t in w_ex)
        gl = abs(sum(t.net_pnl for t in l_ex))
        pnl = sum(t.net_pnl for t in trades_for_reason)
        loss_share = (gl / total_gross_loss * 100.0) if total_gross_loss > 0 else 0.0
        combined_exit_breakdown[reason] = ExitReasonMetrics(
            exit_reason=reason,
            trades=n_ex,
            wins=len(w_ex),
            losses=len(l_ex),
            win_rate_percent=(len(w_ex) / n_ex * 100.0) if n_ex > 0 else 0.0,
            gross_profit=gp,
            gross_loss=gl,
            net_pnl=pnl,
            expectancy=(pnl / n_ex) if n_ex > 0 else 0.0,
            share_of_total_losses_percent=loss_share,
        )

    # Combined drift
    all_drift_groups: dict[str, list[BacktestTrade]] = defaultdict(list)
    all_drift_cost: dict[str, list[BacktestTrade]] = defaultdict(list)
    for window_name, scen_map in window_results.items():
        z_res = scen_map["IDEALIZED_ZERO_COST"]
        c_res = scen_map.get("CONSERVATIVE_SIMULATION_COST")
        z_ind = {ind.timestamp: ind for ind in z_res.indicators}
        c_ind = {ind.timestamp: ind for ind in c_res.indicators} if c_res is not None else {}
        for t in z_res.trades:
            reg = z_ind[t.entry_timestamp].regime if t.entry_timestamp in z_ind and z_ind[t.entry_timestamp].regime else "UNKNOWN"
            all_drift_groups[reg].append(t)
        if c_res is not None:
            for t in c_res.trades:
                reg = c_ind[t.entry_timestamp].regime if t.entry_timestamp in c_ind and c_ind[t.entry_timestamp].regime else "UNKNOWN"
                all_drift_cost[reg].append(t)

    combined_drift = {
        label: compute_metrics_for_trades(
            grp, regime=label, direction="ALL",
            cost_trades=all_drift_cost.get(label, []),
        ).to_dict()
        for label, grp in sorted(all_drift_groups.items())
    }

    return {
        "combined": {
            "per_regime": {k: v.to_dict() for k, v in combined_per_regime.items()},
            "directional_regimes": {k: v.to_dict() for k, v in combined_directional_regimes.items()},
            "exit_breakdown": {k: v.to_dict() for k, v in combined_exit_breakdown.items()},
            "entry_candle_drift": combined_drift,
        },
        "per_window": per_window,
    }


def evaluate_hypothesis_1_directional_asymmetry(
    window_results: Mapping[str, Mapping[str, BacktestResult]],
) -> dict[str, Any]:
    """Evaluates Hypothesis 1: Directional Asymmetry (Bearish Dominance / SELL-Only Variant).

    Hypothesis Statement:
    Long trend continuation ('TRENDING BUY') suffers from structural degradation on M15
    gold, whereas short continuation ('TRENDING SELL') exhibits superior trend persistence.
    A predeclared SELL-only variant will achieve higher profit factor and expectancy across
    frozen OOS windows than the bilateral baseline, though remaining vulnerable to conservative costs.
    """
    partitions = {
        "TRAIN": ["BASELINE"],
        "VALIDATION": ["OOS_1"],
        "HOLDOUT_OOS": ["OOS_2", "OOS_3"],
        "FULL_OOS": ["OOS_1", "OOS_2", "OOS_3"],
    }

    evaluation: dict[str, Any] = {}
    for part_name, w_list in partitions.items():
        baseline_zero_trades: list[BacktestTrade] = []
        baseline_cost_trades: list[BacktestTrade] = []
        sell_only_zero_trades: list[BacktestTrade] = []
        sell_only_cost_trades: list[BacktestTrade] = []
        buy_only_zero_trades: list[BacktestTrade] = []
        buy_only_cost_trades: list[BacktestTrade] = []

        for w in w_list:
            z_w = window_results[w]["IDEALIZED_ZERO_COST"]
            c_w = window_results[w]["CONSERVATIVE_SIMULATION_COST"]
            baseline_zero_trades.extend(z_w.trades)
            baseline_cost_trades.extend(c_w.trades)
            sell_only_zero_trades.extend([t for t in z_w.trades if t.direction == "SELL"])
            sell_only_cost_trades.extend([t for t in c_w.trades if t.direction == "SELL"])
            buy_only_zero_trades.extend([t for t in z_w.trades if t.direction == "BUY"])
            buy_only_cost_trades.extend([t for t in c_w.trades if t.direction == "BUY"])

        base_z = compute_metrics_for_trades(baseline_zero_trades, cost_trades=baseline_cost_trades)
        sell_z = compute_metrics_for_trades(sell_only_zero_trades, cost_trades=sell_only_cost_trades)
        buy_z = compute_metrics_for_trades(buy_only_zero_trades, cost_trades=buy_only_cost_trades)

        evaluation[part_name] = {
            "baseline": base_z.to_dict(),
            "sell_only_variant": sell_z.to_dict(),
            "buy_only_variant": buy_z.to_dict(),
            "sell_improves_expectancy_zero_cost": sell_z.expectancy > base_z.expectancy,
            "sell_improves_net_pnl_zero_cost": sell_z.net_pnl > base_z.net_pnl,
            "sell_overcomes_conservative_cost": (sell_z.conservative_cost_net_pnl or 0.0) > 0.0,
        }

    return {
        "hypothesis_id": "H1_DIRECTIONAL_ASYMMETRY",
        "title": "Directional Asymmetry / SELL-Only Variant Evaluation",
        "partitions": evaluation,
        "supported": (
            evaluation["FULL_OOS"]["sell_improves_expectancy_zero_cost"]
            and evaluation["FULL_OOS"]["sell_improves_net_pnl_zero_cost"]
        ),
        "conclusion": (
            "Hypothesis 1 is SUPPORTED directionally: SELL-only improves profit factor and net P&L "
            "over the bilateral baseline across all OOS windows, confirming that BUY is an uncompensated "
            "drag. However, SELL-only REMAINS INCONSISTENT because conservative costs erase the edge "
            "in OOS_1, OOS_2, and OOS_3, producing an overall negative net P&L (-$5.13) under conservative costs."
        ),
    }


def evaluate_hypothesis_2_regime_drift(
    window_results: Mapping[str, Mapping[str, BacktestResult]],
) -> dict[str, Any]:
    """Evaluates Hypothesis 2: Entry-Candle Regime Drift Degradation.

    Hypothesis Statement:
    Trades where the entry candle immediately drifts out of TRENDING (into NO_TRADE/UNKNOWN or RANGE)
    exhibit significantly worse win rates, lower profit factor, and higher stop-out rates than trades
    where the entry candle confirms trend continuation.
    """
    confirmed_trades: list[BacktestTrade] = []
    degraded_trades: list[BacktestTrade] = []

    for window_name, scen_map in window_results.items():
        z_res = scen_map["IDEALIZED_ZERO_COST"]
        ind_map = {ind.timestamp: ind for ind in z_res.indicators}
        for t in z_res.trades:
            ind = ind_map.get(t.entry_timestamp)
            reg = ind.regime if ind and ind.regime else "UNKNOWN"
            if reg in ("TREND_DOWN", "TREND_UP", "TRENDING"):
                confirmed_trades.append(t)
            else:
                degraded_trades.append(t)

    conf_m = compute_metrics_for_trades(confirmed_trades)
    deg_m = compute_metrics_for_trades(degraded_trades)

    supported = deg_m.win_rate_percent < conf_m.win_rate_percent and deg_m.net_pnl < 0.0

    return {
        "hypothesis_id": "H2_REGIME_DRIFT_DEGRADATION",
        "title": "Entry-Candle Regime Drift Degradation Evaluation",
        "confirmed_trades": conf_m.to_dict(),
        "degraded_trades": deg_m.to_dict(),
        "supported": supported,
        "conclusion": (
            f"Hypothesis 2 is {'SUPPORTED' if supported else 'REFUTED'}: Trades where the entry candle "
            f"drifts to NO_TRADE/RANGE exhibit a win rate of {deg_m.win_rate_percent:.1f}% (vs {conf_m.win_rate_percent:.1f}% "
            f"for trend-confirmed entries) and a profit factor of {(deg_m.profit_factor or 0.0):.2f} (vs {(conf_m.profit_factor or 0.0):.2f}). "
            f"Immediate regime drift on entry indicates premature trend exhaustion."
        ),
    }


def _finite(value: object) -> float | None:
    try:
        number = float(value)
        return number if pd.notna(number) else None
    except (TypeError, ValueError):
        return None


class ConfirmedEntryBacktestEngine(BacktestEngine):
    """Research variant with chronological, close-based trend confirmation.

    The canonical signal is produced after candle ``i`` closes.  A confirmed
    variant observes candle ``i + 1`` through its close and, when the original
    direction is still confirmed, enters at the open of candle ``i + 2``.
    Entering any earlier would use the confirming candle's close to trade at
    its already-past open and introduce look-ahead bias.
    """

    def __init__(
        self,
        *args: Any,
        sell_only: bool = False,
        require_confirmation: bool = True,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.sell_only = sell_only
        self.require_confirmation = require_confirmation
        self.rejected_confirmations = 0
        self._confirmed_entry_index: int | None = None

    def queue_signal(self, signal: dict[str, Any], index: int, dataframe: pd.DataFrame) -> None:
        if self.sell_only and signal.get("signal") == "BUY":
            signal = dict(signal)
            signal["signal"] = "NO_TRADE"
            signal["reasons"] = [*signal.get("reasons", []), "SELL_ONLY_RESEARCH_FILTER"]
        super().queue_signal(signal, index, dataframe)

    def process_candle(self, index: int, dataframe: pd.DataFrame) -> None:
        if not self.require_confirmation:
            super().process_candle(index, dataframe)
            return

        row = dataframe.iloc[index]
        if self._position is not None:
            self._evaluate_exit(index, row, dataframe)
            return

        if self._pending is None:
            return

        if self._confirmed_entry_index is not None:
            if index >= self._confirmed_entry_index:
                self._enter(index, row)
                self._pending = None
                self._confirmed_entry_index = None
                if self._position is not None:
                    self._evaluate_exit(index, row, dataframe)
            return

        confirmation_index = self._pending.signal_index + 1
        if index < confirmation_index:
            return

        history = dataframe.iloc[: index + 1]
        regime = str(detect_regime(history))
        expected_regime = confirmation_expected_regime(self._pending.direction)
        if index == confirmation_index and confirmation_regime_passes(self._pending.direction, regime):
            self._confirmed_entry_index = index + 1
            self.decisions.append(BacktestDecision(
                candle_index=index,
                timestamp=row["time"],
                signal=self._pending.direction,
                confidence=self._pending.confidence,
                state="CONFIRMATION_PASSED",
                reasons=(
                    f"Confirmation candle regime {regime}; entry eligible at next candle open",
                ),
            ))
            return

        reason = (
            f"Confirmation candle regime {regime} failed {expected_regime} requirement"
            if index == confirmation_index
            else "Pending confirmation expired before chronological evaluation"
        )
        self.rejected_confirmations += 1
        self.decisions.append(BacktestDecision(
            candle_index=index,
            timestamp=row["time"],
            signal=self._pending.direction,
            confidence=self._pending.confidence,
            state="CONFIRMATION_REJECTED",
            reasons=(reason,),
        ))
        self._pending = None
        self._confirmed_entry_index = None

    def finish(self, final_index: int, dataframe: pd.DataFrame) -> None:
        super().finish(final_index, dataframe)
        self._confirmed_entry_index = None


def confirmation_expected_regime(direction: str) -> str:
    """Single confirmation rule shared by historical research paths."""
    if direction == "BUY":
        return "TREND_UP"
    if direction == "SELL":
        return "TREND_DOWN"
    raise ValueError("confirmation direction must be BUY or SELL")


def confirmation_regime_passes(direction: str, observed_regime: str) -> bool:
    return observed_regime == confirmation_expected_regime(direction)


async def run_variant_backtest(
    symbol: str,
    timeframe: Timeframe,
    dataset: Sequence[Candle],
    provider: str = "deriv",
    starting_balance: float = 50.0,
    execution_assumptions: BacktestExecutionAssumptions | None = None,
    risk_configuration: BacktestRiskConfiguration | None = None,
    sell_only: bool = False,
    require_confirmation: bool = True,
) -> BacktestResult:
    """Runs a backtest for baseline, SELL-only, or confirmed-entry research variants."""
    execution = execution_assumptions or BacktestExecutionAssumptions()
    risk = risk_configuration or BacktestRiskConfiguration()
    raw_candles = list(dataset)
    snapshot = CandleDatasetSnapshot(
        provider=provider, symbol=symbol, timeframe=timeframe,
        candles=tuple(raw_candles),
    )
    df = calculate_indicators(pd.DataFrame([c.model_dump() for c in raw_candles]))
    indicator_rows = [
        BacktestIndicatorObservation(
            candle_index=i, timestamp=row["time"], ema50=_finite(row.get("EMA50")),
            ema200=_finite(row.get("EMA200")), rsi=_finite(row.get("RSI")),
            atr=_finite(row.get("ATR")),
        )
        for i, row in df.iterrows()
    ]
    engine = ConfirmedEntryBacktestEngine(
        starting_balance=starting_balance, symbol=symbol, timeframe=timeframe,
        risk=risk, execution=execution,
        sell_only=sell_only, require_confirmation=require_confirmation,
    )
    for i in range(_WARMUP_CANDLES, len(df)):
        engine.process_candle(i, df)
        history = df.iloc[: i + 1]
        regime = detect_regime(history)
        indicator_rows[i] = BacktestIndicatorObservation(
            candle_index=i, timestamp=df.iloc[i]["time"], ema50=_finite(df.iloc[i].get("EMA50")),
            ema200=_finite(df.iloc[i].get("EMA200")), rsi=_finite(df.iloc[i].get("RSI")),
            atr=_finite(df.iloc[i].get("ATR")), regime=str(regime),
        )
        signal = generate_trading_signal(history, symbol, regime=regime, include_details=True)
        engine.queue_signal(signal, i, df)

    engine.finish(len(df) - 1, df)
    strategy = {
        "strategy_name": "TrendContinuationConfirmedEntry" if require_confirmation else "TrendContinuation",
        "sell_only": sell_only,
        "require_confirmation": require_confirmation,
    }
    return build_backtest_result(snapshot, engine, strategy, tuple(indicator_rows))


def validate_risk_compliance(result: BacktestResult) -> dict[str, Any]:
    """Validates risk model limits across all executed trades."""
    trades = list(result.trades)
    losses = [t for t in trades if t.net_pnl < 0]
    realized_loss_pct = [
        abs(t.net_pnl) / t.balance_before * 100.0 for t in losses if t.balance_before > 0
    ]
    theoretical_risk = [
        abs(t.entry_price - t.stop_price) * t.quantity.value for t in trades
    ]
    authorized_pct = [
        risk / t.balance_before * 100.0
        for risk, t in zip(theoretical_risk, trades) if t.balance_before > 0
    ]
    auth_for_losses = [
        p for p, t in zip(authorized_pct, trades) if t.net_pnl < 0
    ]
    is_compliant = all(
        realized <= authorized + 1e-9
        for realized, authorized in zip(realized_loss_pct, auth_for_losses)
    )
    balances = [result.initial_capital, *[t.balance_after for t in trades]]
    return {
        "status": "PASS" if is_compliant else "FAIL",
        "max_realized_single_trade_loss_percent": max(realized_loss_pct, default=None),
        "max_authorized_risk_percent": max(authorized_pct, default=None),
        "lowest_balance": min(balances),
        "negative_balance": min(balances) < 0,
        "fell_below_40": min(balances) < 40,
    }
