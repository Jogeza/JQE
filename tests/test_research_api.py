from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from api.app import create_app
from api.research import (
    AcquireHistoryRequest, ExperimentApiRequest, ResearchRequest, VolumeProfileApiRequest, _sessions,
    create_session, get_volume_profile, replay, run_experiment,
)
from backtesting.backtest import run_backtest
from broker.types import Candle, Timeframe
from data.provenance import DatasetProvenance, VolumeType


@pytest.fixture
def candles():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [Candle(time=start+timedelta(minutes=15*i), open=100+i*.1,
                   high=102+i*.1, low=99+i*.1, close=101+i*.1, volume=None,
                   source="fixture") for i in range(210)]


@pytest.mark.asyncio
async def test_replay_prefix_has_no_future_data(candles):
    engine = await run_backtest(dataset=candles, provider="fixture", timeframe=Timeframe.M15)
    session = create_session(candles, engine.result)
    early = replay(session, 200)
    assert len(early.candles) == 201
    assert early.candles[-1].indicators.candle_index == 200
    assert early.candles[-1].indicators.ema50 is not None
    assert all(d.candle_index <= 200 for d in early.signals)
    assert all(p.candle_index <= 200 for p in early.balance_curve)
    assert early.metrics is None
    assert not early.complete
    assert session.metadata.volume_metadata.type == "UNAVAILABLE"
    final = replay(session, 209)
    assert final.complete
    assert final.metrics["ending_capital"] == engine.balance
    assert final.balance_curve[-1].balance == engine.balance
    assert len(final.signals) == 10
    assert session.metadata.dataset.content_hash.startswith("sha256:")
    assert session.metadata.run_fingerprint == engine.result.run_fingerprint
    assert session.metadata.result_hash == engine.result.result_hash
    assert session.metadata.engine_version == engine.result.engine_version
    assert session.metadata.identity_schema_version == engine.result.identity_schema_version


@pytest.mark.asyncio
async def test_same_frozen_dataset_serializes_identically(candles):
    first = await run_backtest(dataset=candles, provider="fixture", timeframe=Timeframe.M15)
    second = await run_backtest(dataset=list(candles), provider="fixture", timeframe=Timeframe.M15)
    assert first.result.to_json_bytes() == second.result.to_json_bytes()
    assert len(first.result.indicators) == len(candles)


@pytest.mark.asyncio
async def test_indicator_at_cursor_does_not_change_with_future_rows(candles):
    prefix = candles[:205]
    short = await run_backtest(dataset=prefix, provider="fixture", timeframe=Timeframe.M15)
    full = await run_backtest(dataset=candles, provider="fixture", timeframe=Timeframe.M15)
    assert short.result.indicators[204] == full.result.indicators[204]


@pytest.mark.asyncio
async def test_trade_outcome_redaction(candles):
    from dataclasses import replace
    from backtesting.models import BacktestTrade, BacktestExitReason
    from broker.types import ExecutionQuantity, ExecutionQuantityUnit
    engine = await run_backtest(dataset=candles, provider="fixture", timeframe=Timeframe.M15)
    trade = BacktestTrade(1, "XAUUSD", Timeframe.M15, "BUY", candles[200].time,
                         candles[201].time, 120, candles[205].time, 125, 118, 125,
                         ExecutionQuantity(value=1, unit=ExecutionQuantityUnit.SIMULATION_UNITS),
                         5, 0, 5, 50, 55, 5, BacktestExitReason.TAKE_PROFIT)
    result = replace(engine.result, trades=(trade,))
    session = create_session(candles, result)
    assert replay(session, 200).trades == []
    pending = replay(session, 201).model_dump(exclude_none=True)["trades"][0]
    assert "exit_index" not in pending
    assert "exit_timestamp" not in pending
    assert "net_pnl" not in pending
    assert "balance_after" not in pending
    assert replay(session, 205).trades[0].net_pnl == 5
    with pytest.raises(HTTPException):
        replay(session, -1)


def test_request_rejects_paths_and_unbounded_work():
    from pydantic import ValidationError
    for values in ({"count": 2001}, {"provider": "../private"}, {"initial_capital": float("inf")}, {"path": "secret"}):
        request = {"provider": "fixture", "symbol": "XAUUSD", "timeframe": "M15", **values}
        with pytest.raises(ValidationError):
            ResearchRequest(**request)


def test_acquisition_request_requires_bounded_aware_aligned_range():
    from pydantic import ValidationError
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    valid = {"provider_symbol": "frxXAUUSD", "timeframe": "M15",
             "requested_start": start, "requested_end": start + timedelta(minutes=15 * 200)}
    assert AcquireHistoryRequest(**valid).timeframe == Timeframe.M15
    for update in ({"requested_start": start.replace(tzinfo=None)},
                   {"requested_end": start + timedelta(minutes=1)},
                   {"requested_end": start + timedelta(minutes=15 * 5000)},
                   {"path": "private.sqlite3"}):
        with pytest.raises(ValidationError):
            AcquireHistoryRequest(**(valid | update))


@pytest.mark.asyncio
async def test_missing_session_and_http_validation():
    app = create_app()
    for method, path, body, expected in (
        ("GET", "/api/v1/research/backtests/missing/replay", b"", 404),
        ("POST", "/api/v1/research/backtests", b'{"path":"secret"}', 422),
    ):
        messages = []
        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}
        async def send(message):
            messages.append(message)
        await app({"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                   "method": method, "scheme": "http", "path": path, "raw_path": path.encode(),
                   "query_string": b"", "headers": [(b"content-type", b"application/json")],
                   "client": ("127.0.0.1", 1), "server": ("localhost", 80)}, receive, send)
        assert messages[0]["status"] == expected


@pytest.mark.asyncio
async def test_volume_profile_endpoint_uses_session_provenance_and_preserves_identity(candles):
    eligible = [item.model_copy(update={"volume": 10}) if hasattr(item, "model_copy") else Candle(
        time=item.time, open=item.open, high=item.high, low=item.low, close=item.close,
        volume=10, source=item.source) for item in candles]
    engine = await run_backtest(dataset=eligible, provider="fixture", timeframe=Timeframe.M15)
    provenance = DatasetProvenance("fixture", "XAUUSD", "M15", "verified ticks", "XAUUSD",
                                   VolumeType.TICK_VOLUME, datetime.now(timezone.utc))
    session = create_session(eligible, engine.result, provenance)
    _sessions[session.metadata.id] = session
    try:
        response = get_volume_profile(session.metadata.id, VolumeProfileApiRequest(
            range_start_index=0, range_end_index=2, bin_size="1", cursor=2))
    finally:
        _sessions.pop(session.metadata.id, None)
    assert response.eligible and response.snapshot is not None
    assert response.snapshot.dataset_identity == session.metadata.dataset.content_hash
    assert response.snapshot.volume_type == "TICK_VOLUME"
    assert response.snapshot.volume_source == "verified ticks"
    assert response.snapshot.range_end_index == 2


@pytest.mark.asyncio
async def test_unavailable_volume_returns_no_profile_and_replay_future_is_rejected(candles):
    engine = await run_backtest(dataset=candles, provider="fixture", timeframe=Timeframe.M15)
    session = create_session(candles, engine.result, DatasetProvenance(
        "fixture", "XAUUSD", "M15", "public candles without volume", "XAUUSD",
        VolumeType.UNAVAILABLE, datetime.now(timezone.utc)))
    _sessions[session.metadata.id] = session
    try:
        unavailable = get_volume_profile(session.metadata.id, VolumeProfileApiRequest(
            range_start_index=0, range_end_index=2, bin_size="1", cursor=2))
        with pytest.raises(HTTPException, match="replay cursor"):
            get_volume_profile(session.metadata.id, VolumeProfileApiRequest(
                range_start_index=0, range_end_index=3, bin_size="1", cursor=2))
    finally:
        _sessions.pop(session.metadata.id, None)
    assert unavailable.eligibility == "VOLUME_UNAVAILABLE"
    assert unavailable.snapshot is None


def test_volume_profile_request_is_bounded_and_rejects_extra_authority():
    from pydantic import ValidationError
    valid = {"range_start_index": 0, "range_end_index": 1, "bin_size": "0.1"}
    for update in ({"range_start_index": -1}, {"bin_size": "0"},
                   {"value_area_fraction": "1.1"}, {"path": "secret.sqlite3"}):
        with pytest.raises(ValidationError):
            VolumeProfileApiRequest(**(valid | update))


@pytest.mark.asyncio
async def test_experiment_endpoint_rejects_unavailable_xauusd_semantics(candles):
    engine = await run_backtest(dataset=candles, provider="deriv", timeframe=Timeframe.M15)
    session = create_session(candles, engine.result)
    _sessions[session.metadata.id] = session
    try:
        result = run_experiment(session.metadata.id, ExperimentApiRequest(
            hypothesis_id="POC_PROXIMITY_FILTER_V1", profile_lookback=20, bin_size="1"))
    finally:
        _sessions.pop(session.metadata.id, None)
    assert result["status"].value == "FRVP_EXPERIMENT_UNAVAILABLE"
    assert result["volume_type"].value == "UNAVAILABLE"


def test_experiment_api_bounds_parameters_and_authority():
    from pydantic import ValidationError
    valid = {"hypothesis_id": "POC_PROXIMITY_FILTER_V1", "profile_lookback": 20, "bin_size": "1"}
    for update in ({"profile_lookback": 201}, {"threshold_candidates": [str(i) for i in range(9)]},
                   {"strategy_code": "arbitrary"}):
        with pytest.raises(ValidationError):
            ExperimentApiRequest(**(valid | update))
