"""Preregister one canonical-v2 experiment before new data/outcomes are read."""
from datetime import datetime, timedelta, timezone

UNIVERSE = tuple(f"{family} Vol {level}" for family in ("FX", "SFX") for level in (20, 40, 60, 80, 99))


def build_protocol(now: datetime) -> dict:
    if now.tzinfo is None:
        raise ValueError("Campaign clock must be timezone-aware")
    today = now.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    validation_start = today + timedelta(days=1)
    test_start = validation_start + timedelta(days=7)
    return {
        "schema_version": 1,
        "registered_at": now.astimezone(timezone.utc).isoformat(),
        "baseline": "jqe-canonical-strategy-v2",
        "entrypoint": "strategy.pipeline.generate_trading_signal",
        "provider": "weltrade", "timeframe": "M5", "symbols": list(UNIVERSE),
        "scope": "Volatility families only; jump families excluded before acquisition",
        "windows": {
            "train": {"start_inclusive": (today - timedelta(days=30)).isoformat(), "end_exclusive": today.isoformat()},
            "validation": {"start_inclusive": validation_start.isoformat(), "end_exclusive": test_start.isoformat()},
            "test": {"start_inclusive": test_start.isoformat(), "end_exclusive": (test_start + timedelta(days=14)).isoformat()},
        },
        "warmup": "200 closed bars preceding each evaluated partition; flat at partition boundaries",
        "embargo": "Registration UTC day excluded; no outcomes in future validation/test are currently available",
        "hypothesis": "Rejecting entries farther than 2.0 ATR from EMA50 improves net expectancy relative to v2 on the identical future test sample",
        "parameter_grid": {"maximum_entry_distance_ema50_atr": [2.0]},
        "maximum_candidate_configurations": 1,
        "training_gate": "Diagnose baseline training losers before implementing the candidate; no candidate if fewer than 100 closed baseline trades",
        "validation_rule": "Evaluate the one frozen candidate once; reject if expectancy delta <=0 at base or doubled spread/commission. No retuning",
        "test_rule": "Evaluate once only after validation passes and code/data/costs are frozen; otherwise leave test sealed",
        "acceptance": {
            "minimum_closed_test_trades_each": 100,
            "positive_net_expectancy_r": True,
            "positive_paired_symbol_day_delta_ci95_lower_bound": True,
            "double_spread_commission_must_pass": True,
            "resampling": "10000 paired circular 3-day block-bootstrap draws; seed 20261008; preserve simultaneous symbols",
            "disclosure": "Equal weight symbol summaries plus pooled trade summaries; no dropping losing symbols; missing symbols block full-universe claims",
        },
        "cost_gate": "Verified contract economics and observed spread/commission evidence required. Slippage must be explicitly stressed, never assumed verified",
        "execution": "No orders, gate changes, safety-state mutation or live-path modifications",
        "strategy_configurations_evaluated": 0, "candidate_configurations_evaluated": 0,
        "status": "PREREGISTERED_NOT_EVALUATED",
    }
