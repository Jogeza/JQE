from datetime import datetime, timedelta, timezone

from broker.types import ClosedMarketObservation, Timeframe
import ast
import inspect

from monitoring import forward_shadow_sampler
from monitoring.forward_shadow_sampler import ForwardShadowSamplerStore, gap_aware_resolver_kwargs
from research.shadow_outcomes import EXIT_GAP_AWARE, ShadowBar


def _observation(index: int) -> ClosedMarketObservation:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=index)
    return ClosedMarketObservation(
        canonical_symbol="PAINX 400", source="test", provider_symbol="PAINX 400",
        timeframe=Timeframe.M1, candle_opened_at=start,
        closed_at=start + timedelta(minutes=1), open=100.0,
        high=101.0, low=99.0, close=100.0, volume=1.0,
    )


def _signal() -> dict:
    return {"intelligence": {
        "atr": 1.0, "trend": "BULLISH", "momentum": "STRONG",
        "volatility": "NORMAL", "liquidity": "GOOD", "regime": "TRENDING",
    }}


def test_sampler_creates_both_sides_every_twenty_bars_and_is_non_overlapping(tmp_path):
    store = ForwardShadowSamplerStore(tmp_path / "forward.sqlite3")
    created = []
    for index in range(40):
        created.append(store.append_for_closed_bar(observation=_observation(index), signal=_signal()))
    assert sum(item.plans_created for item in created) == 4
    specs = store.load_specs()
    assert {(item.side, item.signal_close.minute) for item in specs} == {
        ("BUY", 20), ("SELL", 20), ("BUY", 40), ("SELL", 40)
    }


def test_sampler_restart_is_durable_and_does_not_duplicate(tmp_path):
    path = tmp_path / "forward.sqlite3"
    store = ForwardShadowSamplerStore(path)
    for index in range(20):
        store.append_for_closed_bar(observation=_observation(index), signal=_signal())
    assert len(store.load_specs()) == 2

    restarted = ForwardShadowSamplerStore(path)
    duplicate = restarted.append_for_closed_bar(observation=_observation(19), signal=_signal())
    assert duplicate.plans_created == 0
    assert len(restarted.load_specs()) == 2


def test_forward_resolution_is_gap_aware_and_overshoot_has_no_future_lookahead(tmp_path):
    store = ForwardShadowSamplerStore(tmp_path / "forward.sqlite3")
    for index in range(20):
        store.append_for_closed_bar(observation=_observation(index), signal=_signal())
    spec = next(item for item in store.load_specs() if item.side == "BUY")
    prior = ShadowBar(spec.signal_close - timedelta(minutes=1), 100, 101, 99, 100, 0.1, "test")
    future = ShadowBar(spec.signal_close + timedelta(minutes=1), 100, 1000, 1, 100, 5.0, "test")
    before = gap_aware_resolver_kwargs(spec, [prior])
    after = gap_aware_resolver_kwargs(spec, [prior, future])
    assert before == after
    assert before["exit_mode"] == EXIT_GAP_AWARE


def test_forward_sampler_has_no_execution_or_broker_gateway_dependency():
    tree = ast.parse(inspect.getsource(forward_shadow_sampler))
    imported = []
    attributes = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
        elif isinstance(node, ast.Attribute):
            attributes.append(node.attr)
    assert not any(name == "execution" or name.startswith("execution.") for name in imported)
    assert not any(name in {"broker.factory", "broker.mt5_gateway"} for name in imported)
    assert "submit_order" not in attributes
