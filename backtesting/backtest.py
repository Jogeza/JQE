"""JQE institutional backtest runner.

Loads a fixed historical candle dataset supplied by the caller or from
the local :class:`data.storage.CandleStore`, then replays
JQE's signal -> risk -> execution pipeline candle by candle to produce
performance statistics — the same
:func:`strategy.pipeline.generate_trading_signal` and
:func:`risk.risk_controller.approve_trade` used by ``main.py``'s live
path, so backtest results reflect the actual decision logic.

Run as a script:

    $ python -m backtesting.backtest

Or call :func:`run_backtest` directly for programmatic use.
"""

from __future__ import annotations

import asyncio

import pandas as pd

from analytics.performance import calculate_performance
from backtesting.engine import BacktestEngine
from backtesting.drawdown import balance_drawdown
from backtesting.provenance import source_snapshot
from backtesting.economics import FrozenMarketModel
from collections.abc import Sequence

from broker.types import Candle, Timeframe
from core.exceptions import MarketDataError
from core.indicators import calculate_indicators
from core.logger import logger
from core.regime import detect_regime
from strategy.pipeline import generate_trading_signal
from data.dataset import CandleDatasetManifest, canonical_dataset_hash, verify_dataset_manifest
from data.storage import CandleStore
from backtesting.models import (
    BacktestExecutionAssumptions, BacktestIndicatorObservation, BacktestResult, BacktestRiskConfiguration,
    CandleDatasetSnapshot, backtest_run_fingerprint,
)

DEFAULT_SYMBOL = "XAUUSD"
DEFAULT_TIMEFRAME = Timeframe.M5
DEFAULT_CANDLES = 5000

# Indicators (EMA200, rolling ATR/RSI at window 14) need this many
# leading candles before their values are meaningful — trades aren't
# evaluated before this point.
_WARMUP_CANDLES = 200
_BACKTEST_ENGINE_VERSION = "jqe-backtest-v1"
_DEFAULT_STRATEGY_CONFIGURATION = {
    "strategy_id": "jqe-canonical-strategy-v2",
    "entrypoint": "strategy.pipeline.generate_trading_signal",
    "indicator_engine": "core.indicators.calculate_indicators-v1",
    "regime_engine": "intelligence.market_regime.detect_regime-v2",
}


class BacktestRunner:
    """Explicit configuration wrapper around the canonical backtest entrypoint."""

    def __init__(self, *, symbol: str = DEFAULT_SYMBOL, timeframe: Timeframe = DEFAULT_TIMEFRAME,
                 initial_capital: float = 50.0, provider: str = "unknown",
                 risk_configuration: BacktestRiskConfiguration | None = None,
                 execution_assumptions: BacktestExecutionAssumptions | None = None,
                 strategy_configuration: dict | None = None) -> None:
        self.symbol = symbol
        self.timeframe = timeframe
        self.initial_capital = initial_capital
        self.provider = provider
        self.risk_configuration = risk_configuration
        self.execution_assumptions = execution_assumptions
        self.strategy_configuration = strategy_configuration

    async def run(self, dataset: Sequence[Candle]) -> BacktestResult:
        engine = await run_backtest(
            symbol=self.symbol, timeframe=self.timeframe,
            starting_balance=self.initial_capital, dataset=dataset,
            provider=self.provider, risk_configuration=self.risk_configuration,
            execution_assumptions=self.execution_assumptions,
            strategy_configuration=self.strategy_configuration,
        )
        assert engine.result is not None
        return engine.result


async def run_backtest(
    symbol: str = DEFAULT_SYMBOL,
    timeframe: Timeframe = DEFAULT_TIMEFRAME,
    candles: int = DEFAULT_CANDLES,
    starting_balance: float = 50.0,
    dataset: Sequence[Candle] | None = None,
    store: CandleStore | None = None,
    manifest: CandleDatasetManifest | None = None,
    risk_configuration: BacktestRiskConfiguration | None = None,
    execution_assumptions: BacktestExecutionAssumptions | None = None,
    strategy_configuration: dict | None = None,
    provider: str | None = None,
    start_index: int | None = None,
    end_index: int | None = None,
    market_model: FrozenMarketModel | None = None,
    single_opportunity: tuple[str, int] | None = None,
    long_history_opportunity=None,
    feature_observer=None,
    features_only: bool = False,
) -> BacktestEngine:
    """Runs a full backtest and returns the engine holding its results.

    Args:
        symbol: Instrument symbol to backtest.
        timeframe: Candle timeframe.
        candles: Number of historical candles to load.
        starting_balance: Simulated starting account balance.

    Returns:
        The :class:`~backtesting.engine.BacktestEngine` used for the
        run — inspect ``.statistics()``, ``.trades``, and
        ``.equity_curve`` for results.

    Raises:
        core.exceptions.MarketDataError: If fixed historical market data
            cannot be retrieved, or there isn't enough of it to clear
            the indicator warmup period.
    """
    logger.info("JQE backtest starting for {} ({} candles)", symbol, candles)
    source_identity = source_snapshot()
    if features_only != (feature_observer is not None) or (features_only and (market_model is not None or single_opportunity is not None or long_history_opportunity is not None)):
        raise MarketDataError("Feature-only observation requires an observer and forbids economic replay")

    # Backtests consume a caller-supplied immutable dataset or the durable local
    # cache.  They never construct/connect a broker gateway.
    if dataset is None and provider is None:
        raise MarketDataError(
            "A provider is required when loading a canonical backtest dataset from cache",
            symbol=symbol,
        )
    raw_candles = list(dataset) if dataset is not None else (store or CandleStore()).load_latest(
        symbol, timeframe, candles, provider=provider
    )
    if not raw_candles:
        raise MarketDataError("No fixed historical dataset available", symbol=symbol)
    if any(current.time <= previous.time for previous, current in zip(raw_candles, raw_candles[1:])):
        raise MarketDataError("Historical dataset timestamps must be strictly increasing", symbol=symbol)

    # A supplied manifest represents a previously frozen dataset identity.
    # Verify it before indicators, strategy logic, or simulated execution run.
    if manifest is not None:
        if provider is not None and provider != manifest.provider:
            raise MarketDataError("Provider does not match frozen dataset manifest")
        if manifest.canonical_symbol != symbol:
            raise MarketDataError(
                "Historical dataset manifest symbol does not match backtest",
                manifest_symbol=manifest.canonical_symbol,
                backtest_symbol=symbol,
            )
        if manifest.timeframe != timeframe:
            raise MarketDataError(
                "Historical dataset manifest timeframe does not match backtest",
                manifest_timeframe=manifest.timeframe.value,
                backtest_timeframe=timeframe.value,
            )
        verify_dataset_manifest(manifest, raw_candles)

    df = pd.DataFrame([candle.model_dump() for candle in raw_candles])
    df = calculate_indicators(df)

    def finite(value: object) -> float | None:
        try:
            number = float(value)
            return number if pd.notna(number) else None
        except (TypeError, ValueError):
            return None

    indicator_rows = [
        BacktestIndicatorObservation(
            candle_index=i, timestamp=row["time"], ema50=finite(row.get("EMA50")),
            ema200=finite(row.get("EMA200")), rsi=finite(row.get("RSI")),
            atr=finite(row.get("ATR")),
        )
        for i, row in df.iterrows()
    ]

    if len(df) <= _WARMUP_CANDLES:
        raise MarketDataError(
            "Not enough candles to clear the indicator warmup period",
            symbol=symbol,
            candles=len(df),
            warmup_required=_WARMUP_CANDLES,
        )

    dataset_provider = provider or (manifest.provider if manifest else raw_candles[0].source)
    snapshot = CandleDatasetSnapshot(
        provider=dataset_provider, symbol=symbol, timeframe=timeframe,
        candles=tuple(raw_candles),
    )
    if market_model is not None:
        market_model.validate_dataset(raw_candles, symbol, dataset_provider)
    engine = BacktestEngine(
        starting_balance=starting_balance, symbol=symbol, timeframe=timeframe,
        risk=risk_configuration, execution=execution_assumptions,
        market_model=market_model,
    )

    eval_start = max(_WARMUP_CANDLES, start_index if start_index is not None else _WARMUP_CANDLES)
    eval_end = min(len(df), end_index if end_index is not None else len(df))
    if eval_start >= eval_end:
        raise MarketDataError("Backtest evaluation window is empty or reversed")
    if single_opportunity is not None:
        # Experimental fixed label contract. Fail before simulation on incomplete
        # horizons or attempts to change the registered economics/risk design.
        assumptions = execution_assumptions or BacktestExecutionAssumptions()
        risk = risk_configuration or BacktestRiskConfiguration()
        if (symbol != "SFX Vol 99" or dataset_provider != "weltrade" or timeframe != Timeframe.M5
            or market_model is None or starting_balance != 50.0 or risk != BacktestRiskConfiguration()
            or assumptions != BacktestExecutionAssumptions()
            or type(start_index) is not int or start_index != eval_start
            or end_index != eval_start + assumptions.max_holding_candles + 1
            or eval_end != end_index or len(single_opportunity) != 2
            or single_opportunity[0] not in ("BUY", "SELL")
            or type(single_opportunity[1]) is not int):
            raise MarketDataError("Single-opportunity replay requires the complete frozen label contract")
        times = [c.time for c in raw_candles[eval_start-3:eval_end]]
        from datetime import timedelta
        if any(b-a != timedelta(minutes=5) for a,b in zip(times,times[1:])):
            raise MarketDataError("Single-opportunity replay cannot cross a gap")
    target = single_opportunity
    if long_history_opportunity is not None:
        from backtesting.long_history_labels import LongHistoryOpportunity
        if single_opportunity is not None or type(long_history_opportunity) is not LongHistoryOpportunity:
            raise MarketDataError("Separate longer-history opportunity contract required")
        long_history_opportunity.validate(
            symbol=symbol, provider=dataset_provider, timeframe=timeframe, candles=raw_candles,
            model=market_model, capital=starting_balance, start=start_index, end=end_index,
            risk=risk_configuration or BacktestRiskConfiguration(),
            execution=execution_assumptions or BacktestExecutionAssumptions(),
        )
        target = (long_history_opportunity.direction, long_history_opportunity.confidence)
    run_context = {
        "provider": dataset_provider,
        "candle_source": raw_candles[0].source,
        "manifest_content_hash": manifest.content_hash if manifest else None,
        "evaluation": {
            "start_index_inclusive": eval_start, "end_index_exclusive": eval_end,
            "first_candle": raw_candles[eval_start].time.isoformat(),
            "last_candle": raw_candles[eval_end - 1].time.isoformat(),
            "warmup_candles": _WARMUP_CANDLES,
        },
        "source_snapshot": source_identity,
    }
    if market_model is not None:
        run_context["frozen_market_model"] = market_model.identity()
    if single_opportunity is not None:
        run_context["single_opportunity"] = {
            "protocol": "jqe-counterfactual-training-labels-v1",
            "expected_signal": list(single_opportunity),
            "claim_scope": "INDEPENDENT_OPPORTUNITY_NOT_STATEFUL_STRATEGY_PERFORMANCE",
        }

    if long_history_opportunity is not None:
        from dataclasses import asdict
        run_context["long_history_opportunity"] = asdict(long_history_opportunity)

    for i in range(eval_start, eval_end):
        if not features_only:
            engine.process_candle(i, df)
        if target is not None and i != eval_start:
            continue  # Manage the target only; never queue a later entry.
        history = df.iloc[: i + 1]
        regime = detect_regime(history)
        indicator_rows[i] = BacktestIndicatorObservation(
            candle_index=i, timestamp=df.iloc[i]["time"], ema50=finite(df.iloc[i].get("EMA50")),
            ema200=finite(df.iloc[i].get("EMA200")), rsi=finite(df.iloc[i].get("RSI")),
            atr=finite(df.iloc[i].get("ATR")), regime=str(regime),
        )
        signal = generate_trading_signal(history, symbol, regime=regime, include_details=True)
        if features_only:
            feature_observer(i, history, signal)
            continue
        if target is not None and (signal.get("signal"), signal.get("confidence")) != target:
            raise MarketDataError("Target signal differs from original canonical observation")
        engine.queue_signal(signal, i, df)

    if features_only:
        if source_snapshot() != source_identity:
            raise MarketDataError("Feature recording source changed during replay")
        return engine  # No result/performance: observing decisions is not a backtest return.
    engine.finish(eval_end - 1, df)
    if target is not None and (
        len(engine.trades) > 1 or any(t.exit_reason.value == "END_OF_DATA" for t in engine.trades)
    ):
        raise MarketDataError("Single-opportunity replay violated one-entry/full-horizon contract")
    if source_snapshot() != source_identity:
        raise MarketDataError("Research source/dependencies changed during replay; discard run")

    basic_stats = engine.statistics()
    logger.info("JQE backtest results: {}", basic_stats)

    if engine.trades:
        institutional_metrics = calculate_performance(engine.trades, engine.equity_curve)
        logger.info("Institutional metrics: {}", institutional_metrics)
    else:
        logger.warning("No trades were taken during this backtest run")

    engine.result = build_backtest_result(
        snapshot, engine,
        strategy_configuration or _DEFAULT_STRATEGY_CONFIGURATION,
        tuple(indicator_rows),
        run_context=run_context,
    )

    return engine


def build_backtest_result(
    dataset: CandleDatasetSnapshot, engine: BacktestEngine, strategy: dict,
    indicators: tuple[BacktestIndicatorObservation, ...] = (),
    *, run_context: dict | None = None,
) -> BacktestResult:
    pnls = [trade.net_pnl for trade in engine.trades]
    wins, losses = [p for p in pnls if p > 0], [p for p in pnls if p < 0]
    break_even = len(pnls) - len(wins) - len(losses)
    gross_profit, gross_loss = sum(wins), abs(sum(losses))
    if gross_loss:
        profit_factor, pf_status = gross_profit / gross_loss, "DEFINED"
    elif gross_profit:
        profit_factor, pf_status = None, "POSITIVE_WITHOUT_LOSSES"
    else:
        profit_factor, pf_status = None, "UNDEFINED_NO_PROFIT_OR_LOSS"
    peak = engine.equity_curve[0]
    max_dd = max_dd_pct = 0.0
    drawdown_curve = [engine.starting_balance, *(o.equity for o in engine.equity_observations)] if engine.market_model is not None else engine.equity_curve
    for balance in drawdown_curve:
        peak, drawdown, percent = balance_drawdown(balance, peak)
        if drawdown > max_dd:
            max_dd, max_dd_pct = drawdown, percent
    max_wins = max_losses = win_run = loss_run = 0
    for pnl in pnls:
        win_run, loss_run = ((win_run + 1, 0) if pnl > 0 else (0, loss_run + 1) if pnl < 0 else (0, 0))
        max_wins, max_losses = max(max_wins, win_run), max(max_losses, loss_run)
    count = len(pnls)
    dataset_hash = canonical_dataset_hash(
        dataset.candles, symbol=dataset.symbol, timeframe=dataset.timeframe
    )
    run_fingerprint = backtest_run_fingerprint(
        dataset_hash=dataset_hash, symbol=dataset.symbol, timeframe=dataset.timeframe,
        initial_capital=engine.starting_balance, strategy=strategy,
        risk=engine.risk_configuration, execution=engine.execution_assumptions,
        engine_version=_BACKTEST_ENGINE_VERSION,
        run_context=run_context,
    )
    return BacktestResult(
        identity_schema_version=2 if run_context is not None else 1, engine_version=_BACKTEST_ENGINE_VERSION,
        dataset_hash=dataset_hash, run_fingerprint=run_fingerprint,
        provider=dataset.provider, symbol=dataset.symbol, timeframe=dataset.timeframe,
        dataset_start=dataset.start, dataset_end=dataset.end, candle_count=len(dataset.candles),
        initial_capital=engine.starting_balance, strategy=dict(strategy),
        risk=engine.risk_configuration, execution=engine.execution_assumptions,
        ending_capital=engine.balance, absolute_pnl=engine.balance-engine.starting_balance,
        return_percent=(engine.balance-engine.starting_balance)/engine.starting_balance*100,
        total_trades=count, winning_trades=len(wins), losing_trades=len(losses), break_even_trades=break_even,
        win_rate_percent=(len(wins)/count*100 if count else 0.0), gross_profit=gross_profit,
        gross_loss=gross_loss, profit_factor=profit_factor, profit_factor_status=pf_status,
        average_trade_pnl=(sum(pnls)/count if count else 0.0),
        average_winner=(sum(wins)/len(wins) if wins else None), average_loser=(sum(losses)/len(losses) if losses else None),
        largest_winner=(max(wins) if wins else None), largest_loser=(min(losses) if losses else None),
        expectancy=(sum(pnls)/count if count else 0.0), maximum_drawdown=max_dd,
        maximum_drawdown_percent=max_dd_pct, drawdown_basis="BAR_CLOSE_LIQUIDATION_EQUITY" if engine.market_model is not None else "REALIZED_BALANCE",
        average_holding_candles=(sum(t.holding_candles for t in engine.trades)/count if count else 0.0),
        maximum_consecutive_wins=max_wins, maximum_consecutive_losses=max_losses,
        trades=tuple(engine.trades),
        decisions=tuple(engine.decisions),
        indicators=indicators,
        run_context=run_context or {},
        equity_observations=tuple(engine.equity_observations),
    )


if __name__ == "__main__":
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--entry-quality-audit", type=Path, metavar="NEW_OUTPUT_DIRECTORY",
                        help="Audit frozen Weltrade M5 bundles offline; never connects a gateway")
    parser.add_argument("--qualify-research-data", type=Path, metavar="NEW_OUTPUT_DIRECTORY",
                        help="Inventory frozen M5 provenance offline without replay or terminal access")
    parser.add_argument("--campaign-training", type=Path, help="Frozen campaign directory; training diagnostics only")
    parser.add_argument("--cost-terms", type=Path, help="Frozen additional contract/margin terms JSON")
    parser.add_argument("--opportunity-inventory", type=Path, help="Extract saved training opportunities; no new replay")
    parser.add_argument("--inventory-campaign", type=Path, help="Frozen acquisition manifests for opportunity inventory")
    parser.add_argument("--register-counterfactual-labels", type=Path, help="Saved training directory; freeze label design without outcomes")
    parser.add_argument("--counterfactual-pilot", type=Path, help="Frozen label registration; first-three-event implementation pilot")
    parser.add_argument("--counterfactual-campaign", type=Path, help="Full registered training label campaign; no ML fit")
    parser.add_argument("--resume-labels-from", type=Path, help="Preserved interrupted full campaign; validate and reuse completed labels")
    parser.add_argument("--output", type=Path, help="New training diagnostic output directory")
    parser.add_argument("--record-training-features", type=Path, help="Frozen feature contract; canonical decisions without economic replay")
    parser.add_argument("--qualify-feature-label-joins", type=Path, help="NEWDIR for saved training evidence joins and purge diagnostics")
    parser.add_argument("--audit-long-history-labels", type=Path, help="Offline saved full-label coverage audit; registration path")
    parser.add_argument("--qualify-long-label-storage", type=Path, help="NEWDIR for lossless saved-pilot shared-storage qualification; no replay")
    parser.add_argument("--profile-long-label-attempt", type=Path, help="Fixed first SFX99 zero-cost TRAIN target; canonical replay profile only")
    parser.add_argument("--qualify-long-label-serialization", type=Path, help="NEWDIR for all90 saved golden serializer comparisons; no replay")
    parser.add_argument("--qualify-long-label-transition-replays", type=Path, help="Frozen registration; fixed two executed/one null canonical equivalence examples")
    parser.add_argument("--qualify-long-label-source-transition", type=Path, help="Frozen registration; exact stopped-segment source transition evidence")
    parser.add_argument("--qualify-long-label-lineage", type=Path, help="NEWDIR for exact integration/source lineage qualification; no replay")
    parser.add_argument("--long-label-transition", type=Path, help="Exact qualified source-lineage contract; opt-in full resume/audit only")
    parser.add_argument("--long-history-label-campaign", type=Path, help="Full frozen all-symbol training-label dispatch")
    parser.add_argument("--resume-long-labels-from", type=Path, action="append", default=[], help="Prior immutable full dispatch directories; repeat for each segment")
    parser.add_argument("--long-history-label-pilot", type=Path, help="Separate frozen all-symbol label pilot; first three eligible events per symbol")
    parser.add_argument("--long-history-training", type=Path, help="Separate frozen longer-history TRAIN registration")
    parser.add_argument("--preflight-only", action="store_true", help="Verify longer-history inputs without outcomes")
    args = parser.parse_args()
    if args.long_label_transition and not (args.long_history_label_campaign or args.audit_long_history_labels):
        parser.error("--long-label-transition requires full label resume or audit")
    if args.resume_long_labels_from and not (args.long_history_label_campaign or args.audit_long_history_labels):
        parser.error("--resume-long-labels-from requires --long-history-label-campaign")
    if args.preflight_only and not args.long_history_training:
        parser.error("--preflight-only requires --long-history-training")
    if args.resume_labels_from and not args.counterfactual_campaign:
        parser.error("--resume-labels-from requires --counterfactual-campaign")
    if sum(bool(x) for x in (args.qualify_long_label_lineage,args.qualify_long_label_source_transition,args.qualify_long_label_transition_replays,args.qualify_long_label_serialization,args.profile_long_label_attempt,args.qualify_long_label_storage,args.audit_long_history_labels,args.long_history_label_campaign,args.long_history_label_pilot,args.long_history_training,args.qualify_feature_label_joins,args.record_training_features,args.entry_quality_audit,args.qualify_research_data,args.campaign_training,args.opportunity_inventory,args.register_counterfactual_labels,args.counterfactual_pilot,args.counterfactual_campaign)) > 1:
        parser.error("Select one research operation")
    if args.qualify_long_label_lineage:
        from backtesting.long_history_lineage import qualify
        qualify(args.qualify_long_label_lineage)
    elif args.qualify_long_label_source_transition:
        if not args.output:
            parser.error("Source transition requires --output NEWDIR")
        from backtesting.source_transition import qualify
        qualify(args.qualify_long_label_source_transition,Path('reports/long-history-label-campaign-20261009-01'),
                args.output,Path('reports/source-transition-replays-20261010-02/audit.json'))
    elif args.qualify_long_label_transition_replays:
        if not args.output:
            parser.error("Transition replay qualification requires --output NEWDIR")
        from backtesting.long_history_label_profile import qualify_transition_replays
        asyncio.run(qualify_transition_replays(args.qualify_long_label_transition_replays,args.output,run_backtest))
    elif args.qualify_long_label_serialization:
        from backtesting.serialization_qualification import qualify
        qualify(args.qualify_long_label_serialization)
    elif args.profile_long_label_attempt:
        if not args.output:
            parser.error("Replay profile requires --output NEWDIR")
        from backtesting.long_history_label_profile import profile_attempt
        asyncio.run(profile_attempt(args.profile_long_label_attempt,args.output,run_backtest))
    elif args.qualify_long_label_storage:
        from backtesting.long_history_result_store import qualify_storage
        qualify_storage(args.qualify_long_label_storage)
    elif args.audit_long_history_labels:
        if not args.output or not args.resume_long_labels_from:
            parser.error("Full label audit requires --output NEWDIR and every --resume-long-labels-from segment")
        from backtesting.long_history_label_audit import audit
        audit(args.audit_long_history_labels,args.resume_long_labels_from,args.output,transition_path=args.long_label_transition)
    elif args.long_history_label_campaign:
        if not args.output:
            parser.error("Full label dispatch requires --output NEWDIR")
        from backtesting.long_history_labels import pilot
        asyncio.run(pilot(args.long_history_label_campaign,args.output,run_backtest,full_campaign=True,resume_from=args.resume_long_labels_from,transition_path=args.long_label_transition))
    elif args.long_history_label_pilot:
        if not args.output:
            parser.error("Longer-history label pilot requires --output NEWDIR")
        from backtesting.long_history_labels import pilot
        asyncio.run(pilot(args.long_history_label_pilot,args.output,run_backtest))
    elif args.long_history_training:
        if not args.output:
            parser.error("Longer-history training requires --output NEWDIR")
        from backtesting.long_history_training import dispatch
        asyncio.run(dispatch(args.long_history_training,args.output,run_backtest,preflight_only=args.preflight_only))
    elif args.qualify_feature_label_joins:
        from backtesting.join_qualification import qualify
        qualify(args.qualify_feature_label_joins)
    elif args.record_training_features:
        if not args.output:
            parser.error("Feature recording requires --output NEWDIR")
        from backtesting.feature_recorder import record
        asyncio.run(record(args.record_training_features,args.output,run_backtest))
    elif args.counterfactual_pilot or args.counterfactual_campaign:
        if not args.inventory_campaign or not args.cost_terms or not args.output:
            parser.error("Counterfactual pilot requires --inventory-campaign, --cost-terms and --output")
        from backtesting.label_pilot import pilot
        asyncio.run(pilot(args.counterfactual_campaign or args.counterfactual_pilot,args.inventory_campaign,args.cost_terms,args.output,run_backtest,
            full_campaign=bool(args.counterfactual_campaign),resume_from=args.resume_labels_from))
    elif args.register_counterfactual_labels:
        if not args.inventory_campaign or not args.cost_terms or not args.output:
            parser.error("Counterfactual registration requires --inventory-campaign, --cost-terms and --output")
        from backtesting.label_protocol import register
        register(args.register_counterfactual_labels, args.inventory_campaign, args.cost_terms, args.output)
    elif args.opportunity_inventory:
        if not args.inventory_campaign or not args.output:
            parser.error("Opportunity inventory requires --inventory-campaign and --output")
        from backtesting.opportunity_inventory import inventory
        inventory(args.opportunity_inventory, args.inventory_campaign, args.output)
    elif args.campaign_training:
        if not args.cost_terms or not args.output:
            parser.error("Campaign training requires --cost-terms and --output")
        from backtesting.campaign_baseline import training_baseline
        asyncio.run(training_baseline(args.campaign_training,args.cost_terms,args.output,run_backtest))
    elif args.qualify_research_data:
        from backtesting.qualification import qualify_bundles
        qualify_bundles(args.qualify_research_data)
    elif args.entry_quality_audit:
        from backtesting.entry_quality import audit_baseline
        asyncio.run(audit_baseline(args.entry_quality_audit, run_backtest))
    else:
        asyncio.run(run_backtest())
