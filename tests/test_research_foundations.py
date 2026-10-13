"""Regression coverage for window/source identity and offline qualification."""
import pytest

from backtesting.backtest import run_backtest
from backtesting.qualification import qualify_bundles
from core.exceptions import MarketDataError
from tests.test_backtest_reproducibility import _candles


async def test_window_and_provider_are_bound_to_run_identity():
    candles = _candles()
    first = (await run_backtest(dataset=candles, provider="fixture-a", end_index=220)).result
    second = (await run_backtest(dataset=candles, provider="fixture-a", end_index=221)).result
    other = (await run_backtest(dataset=candles, provider="fixture-b", end_index=220)).result
    assert first.dataset_hash == second.dataset_hash == other.dataset_hash
    assert len({r.run_fingerprint for r in (first, second, other)}) == 3
    assert first.identity_schema_version == 2
    assert first.run_context["evaluation"]["end_index_exclusive"] == 220


async def test_empty_evaluation_window_rejected():
    with pytest.raises(MarketDataError, match="empty or reversed"):
        await run_backtest(dataset=_candles(), start_index=225, end_index=220)


async def test_concurrent_source_change_rejects_result(monkeypatch):
    snapshots = iter(({"files": {"a": "1"}}, {"files": {"a": "2"}}))
    monkeypatch.setattr("backtesting.backtest.source_snapshot", lambda: next(snapshots))
    with pytest.raises(MarketDataError, match="changed during replay"):
        await run_backtest(dataset=_candles())


async def test_dependency_change_changes_run_identity(monkeypatch):
    monkeypatch.setattr("backtesting.backtest.source_snapshot", lambda: {"dependencies": {"python": "a"}})
    first = (await run_backtest(dataset=_candles())).result
    monkeypatch.setattr("backtesting.backtest.source_snapshot", lambda: {"dependencies": {"python": "b"}})
    second = (await run_backtest(dataset=_candles())).result
    assert first.run_fingerprint != second.run_fingerprint


def test_qualification_rejects_corrupt_bundle_without_replay(tmp_path):
    bundles = tmp_path / "bundles"
    (bundles / "bad_M5").mkdir(parents=True)
    output = tmp_path / "evidence"
    report = qualify_bundles(output, bundles)
    assert report["status"] == "BLOCKED_NEEDS_QUALIFIED_DATA"
    assert report["candidate_configurations_tried"] == 0
    assert report["bundles"][0]["promotion_status"] == "BLOCKED"
    assert "load_error" in report["bundles"][0]
    with pytest.raises(FileExistsError):
        qualify_bundles(output, bundles)
