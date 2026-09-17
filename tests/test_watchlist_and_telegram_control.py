"""Tests for Stage 4 + 5: Synthetic-index watchlist persistence, API, daemon dynamic reload, Telegram control, and daily digest."""

from __future__ import annotations

import ast
from datetime import datetime, timezone
import inspect
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from broker.types import Timeframe
from config.settings import Settings
from data import watchlist as watchlist_module
from data.watchlist import DEFAULT_SYNTHETIC_SEEDS, WatchPair, WatchlistItem, WatchlistStore
from api import watchlist as api_watchlist_module
from api.watchlist import (
    WatchlistAddRequest,
    WatchlistResponse,
    add_to_watchlist,
    delete_from_watchlist_path,
    delete_from_watchlist_query,
    get_watchlist,
)
from monitoring.observation_daemon import DaemonConfig, ObservationDaemon
from notifications import telegram as telegram_module
from notifications.telegram import (
    InstrumentDigestSnapshot,
    TelegramCommandProcessor,
    TelegramDigestService,
    TelegramGateway,
    TelegramConfig,
    format_daily_digest,
)


def test_watchlist_store_seeds_synthetics_and_persists(tmp_path: Path) -> None:
    db_path = tmp_path / "watchlist.sqlite3"
    store = WatchlistStore(db_path)
    items = store.get_items()
    assert len(items) == len(DEFAULT_SYNTHETIC_SEEDS)
    symbols = [item.symbol for item in items]
    assert "R_75" in symbols
    assert "FX VOL 20" in symbols
    assert "PAINX 400" in symbols
    assert all(item.timeframe == "H1" for item in items)

    # Add a new instrument
    added = store.add_item("TrendX 1000", "H1")
    assert added.symbol == "TRENDX 1000"
    assert added.timeframe == "H1"
    assert added.scope == "TRENDX 1000:H1"

    # Simulate restart by instantiating a new store pointing to the same file
    restarted_store = WatchlistStore(db_path)
    restarted_items = restarted_store.get_items()
    restarted_symbols = [item.symbol for item in restarted_items]
    assert "TRENDX 1000" in restarted_symbols

    # Remove an instrument
    assert restarted_store.remove_item("TRENDX 1000", "H1") is True
    assert "TRENDX 1000" not in [i.symbol for i in restarted_store.get_items()]

    # Reopen again and verify removal persisted
    third_store = WatchlistStore(db_path)
    assert "TRENDX 1000" not in [i.symbol for i in third_store.get_items()]


def test_watchlist_api_endpoints(tmp_path: Path) -> None:
    db_path = tmp_path / "api_watchlist.sqlite3"
    store = WatchlistStore(db_path)

    # 1. GET initial watchlist (seeded)
    initial_resp = get_watchlist(store=store)
    assert isinstance(initial_resp, WatchlistResponse)
    assert initial_resp.count == len(DEFAULT_SYNTHETIC_SEEDS)
    assert any(i.symbol == "R_75" for i in initial_resp.items)

    # 2. POST add instrument
    req = WatchlistAddRequest(symbol="QuadX 2000", timeframe="M15")
    added_dto = add_to_watchlist(request=req, store=store)
    assert added_dto.symbol == "QUADX 2000"
    assert added_dto.timeframe == "M15"
    assert added_dto.scope == "QUADX 2000:M15"

    # 3. Verify it appears in GET
    after_add = get_watchlist(store=store)
    assert any(i.symbol == "QUADX 2000" and i.timeframe == "M15" for i in after_add.items)

    # 4. DELETE instrument by path
    del_resp = delete_from_watchlist_path(symbol="QUADX 2000", timeframe="M15", store=store)
    assert del_resp.deleted is True
    assert del_resp.symbol == "QUADX 2000"

    # 5. Verify it is removed
    after_del = get_watchlist(store=store)
    assert not any(i.symbol == "QUADX 2000" for i in after_del.items)

    # 6. DELETE instrument by query
    req2 = WatchlistAddRequest(symbol="MAX 1000", timeframe="H1")
    add_to_watchlist(request=req2, store=store)
    del_query_resp = delete_from_watchlist_query(symbol="MAX 1000", timeframe=None, store=store)
    assert del_query_resp.deleted is True
    assert not any(i.symbol == "MAX 1000" for i in get_watchlist(store=store).items)

    # 7. Invalid timeframe rejection raises HTTPException 400
    with pytest.raises(HTTPException) as exc_info:
        add_to_watchlist(request=WatchlistAddRequest(symbol="R_50", timeframe="INVALID_TF"), store=store)
    assert exc_info.value.status_code == 400


def test_daemon_picks_up_watchlist_changes_without_restart(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon_wl.sqlite3"
    store = WatchlistStore(db_path, default_seeds=[("R_75", "H1")])

    config = DaemonConfig(
        watches=(WatchPair("R_75", Timeframe.H1),),
        evidence_path=tmp_path / "daemon.evidence.sqlite3",
        close_grace_seconds=5.0,
        max_backoff_seconds=30.0,
        heartbeat_stale_cycles=2,
        watchlist_store=store,
        poll_interval_seconds=1.0,
    )
    daemon = ObservationDaemon(config, lambda: MagicMock(), watchlist_store=store)

    # Initial watches
    initial_watches = daemon.get_active_watches()
    assert len(initial_watches) == 1
    assert initial_watches[0].symbol == "R_75"

    # Add instrument externally into the store (as would happen via API or Telegram)
    store.add_item("FX Vol 20", "H1")

    # Without restarting daemon, get_active_watches picks up the new pair
    updated_watches = daemon.get_active_watches()
    symbols = [w.symbol for w in updated_watches]
    assert "R_75" in symbols
    assert "FX VOL 20" in symbols
    assert len(updated_watches) == 2

    # Remove instrument
    store.remove_item("R_75", "H1")
    after_remove_watches = daemon.get_active_watches()
    after_symbols = [w.symbol for w in after_remove_watches]
    assert "R_75" not in after_symbols
    assert "FX VOL 20" in after_symbols
    assert len(after_remove_watches) == 1


@pytest.mark.asyncio
async def test_telegram_admin_commands_succeed_and_unauthorized_chats_ignored(tmp_path: Path) -> None:
    store = WatchlistStore(tmp_path / "tg_watchlist.sqlite3", default_seeds=[("R_75", "H1")])
    admin_chat_id = 777
    unauthorized_chat_id = 999

    mock_reads = MagicMock()
    mock_digest_provider = AsyncMock()
    mock_digest_provider.get_digest_snapshots.return_value = [
        InstrumentDigestSnapshot("R_75", "H1", "BUY", 85.0, True, 5, 20)
    ]

    processor = TelegramCommandProcessor(
        allowed_chat_id=admin_chat_id,
        read_model=mock_reads,
        watchlist_model=store,
        digest_provider=mock_digest_provider,
    )

    def msg(text: str, chat_id: int) -> dict:
        return {"message": {"chat": {"id": chat_id}, "text": text}}

    # 1. Unauthorized chat sends /watchlist -> ignored (returns None)
    assert await processor.process_update(msg("/watchlist", unauthorized_chat_id)) is None

    # 2. Unauthorized chat sends /add -> ignored (returns None, store unchanged)
    assert await processor.process_update(msg("/add PainX 400 H1", unauthorized_chat_id)) is None
    assert "PAINX 400" not in [i.symbol for i in store.get_items()]

    # 3. Admin chat sends /watchlist -> succeeds
    admin_wl = await processor.process_update(msg("/watchlist", admin_chat_id))
    assert admin_wl is not None
    assert "WATCHLIST" in admin_wl
    assert "R_75 (H1)" in admin_wl

    # 4. Admin chat sends /add -> succeeds and mutates store
    add_resp = await processor.process_update(msg("/add PainX 400 H1", admin_chat_id))
    assert add_resp is not None
    assert "ADDED TO WATCHLIST: PAINX 400 (H1)" in add_resp
    assert "PAINX 400" in [i.symbol for i in store.get_items()]

    # 5. Admin chat sends /remove -> succeeds and mutates store
    rem_resp = await processor.process_update(msg("/remove PainX 400 H1", admin_chat_id))
    assert rem_resp is not None
    assert "REMOVED FROM WATCHLIST: PAINX 400 (H1)" in rem_resp
    assert "PAINX 400" not in [i.symbol for i in store.get_items()]

    # 6. Admin chat sends /digest -> succeeds
    digest_resp = await processor.process_update(msg("/digest", admin_chat_id))
    assert digest_resp is not None
    assert "DAILY MARKET &amp; WATCHLIST DIGEST" in digest_resp
    assert "R_75 (H1)" in digest_resp
    assert "5/20" in digest_resp


def test_digest_content_accuracy_against_fixtures() -> None:
    fixtures = [
        InstrumentDigestSnapshot(
            symbol="R_75",
            timeframe="H1",
            conclusion="BUY",
            quality_score=85,
            is_steady=True,
            cap_count=7,
            cap_limit=20,
        ),
        InstrumentDigestSnapshot(
            symbol="FX Vol 20",
            timeframe="H1",
            conclusion="NO_TRADE",
            quality_score=42,
            is_steady=False,
            cap_count=0,
            cap_limit=20,
        ),
        InstrumentDigestSnapshot(
            symbol="PainX 400",
            timeframe="H1",
            conclusion="SELL",
            quality_score=78,
            is_steady=True,
            cap_count=20,
            cap_limit=20,
        ),
    ]

    fixed_time = datetime(2026, 9, 17, 8, 0, 0, tzinfo=timezone.utc)
    digest = format_daily_digest(fixtures, as_of=fixed_time)

    assert "<b>DAILY MARKET &amp; WATCHLIST DIGEST</b>" in digest
    assert "Date: 2026-09-17 UTC" in digest
    assert "Active Instruments: 3" in digest

    # Check R_75
    assert "<b>R_75 (H1)</b>" in digest
    assert "• Conclusion: BUY" in digest
    assert "• Quality Score: 85" in digest
    assert "• Steady / Worth Trading: YES (STEADY)" in digest
    assert "• Daily Cap Usage: 7/20" in digest

    # Check FX Vol 20
    assert "<b>FX Vol 20 (H1)</b>" in digest
    assert "• Conclusion: NO_TRADE" in digest
    assert "• Quality Score: 42" in digest
    assert "• Steady / Worth Trading: NO (UNSTEADY)" in digest
    assert "• Daily Cap Usage: 0/20" in digest

    # Check PainX 400
    assert "<b>PainX 400 (H1)</b>" in digest
    assert "• Conclusion: SELL" in digest
    assert "• Quality Score: 78" in digest
    assert "• Steady / Worth Trading: YES (STEADY)" in digest
    assert "• Daily Cap Usage: 20/20" in digest


@pytest.mark.asyncio
async def test_digest_service_sends_to_gateway() -> None:
    mock_gateway = AsyncMock()
    mock_provider = AsyncMock()
    mock_provider.get_digest_snapshots.return_value = [
        InstrumentDigestSnapshot("R_75", "H1", "BUY", 80, True, 2, 20)
    ]
    service = TelegramDigestService(mock_gateway, mock_provider)
    result = await service.send_digest()
    assert "DAILY MARKET &amp; WATCHLIST DIGEST" in result
    mock_gateway.send_text.assert_awaited_once_with(result)


def test_structural_isolation_no_execution_in_watchlist_or_telegram() -> None:
    """Assert zero executor/order/submission/policy imports in watchlist and telegram modules."""
    forbidden_tokens = (
        "AsyncTradeExecutor",
        "OrderRequest",
        "OrderSide",
        "submit_order",
        "order_send",
        "execution.policy",
        "ExecutionPolicy",
        "ExecutionIntent",
        "SQLiteOneShotExecutionGuard",
        "DailyInstrumentTradeGuard",
    )

    modules = (watchlist_module, api_watchlist_module, telegram_module)
    for mod in modules:
        source = inspect.getsource(mod)
        for token in forbidden_tokens:
            assert token not in source, f"Forbidden token '{token}' found in {mod.__name__}"

        # AST analysis for imports
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("execution"), (
                        f"Forbidden import '{alias.name}' in {mod.__name__}"
                    )
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    assert not node.module.startswith("execution"), (
                        f"Forbidden import from '{node.module}' in {mod.__name__}"
                    )


def test_digest_assembler_real_evidence_to_snapshot(tmp_path: Path) -> None:
    from dataclasses import asdict
    from execution.daily_instrument_guard import DailyInstrumentTradeGuard
    from monitoring.observation_daemon import (
        DigestAssembler,
        ObservationDaemonStore,
        _TRADEABLE_QUALITY,
    )
    from research.campaign_provenance import CampaignEvidence, canonical_json

    store = ObservationDaemonStore(tmp_path / "evidence.sqlite3", "test-session")
    guard = DailyInstrumentTradeGuard(tmp_path / "guard.sqlite3", limit=20)
    pair = WatchPair("R_75", Timeframe.H1)
    now = datetime(2026, 9, 17, 8, 0, 0, tzinfo=timezone.utc)

    # Seed real evidence for R_75
    facts = {
        "symbol": "R_75",
        "timeframe": "H1",
        "conclusion": "BUY",
        "quality_score": 82.0,
        "confidence": 82.0,
        "quality": "HIGH",
        "data_freshness": "fresh",
        "regime": "TRENDING",
        "observed_at": now.isoformat(),
        "candle_closed_at": now.isoformat(),
        "expires_at": now.isoformat(),
        "missed_candles": 0,
    }
    event_id = f"observation-{pair.scope}-{now.isoformat()}"
    event = CampaignEvidence(event_id, "SIGNAL", None, now.isoformat(), facts)
    with store._connect() as conn:
        conn.execute(
            "INSERT INTO evidence VALUES (?,?,?)",
            ("test-session", event_id, canonical_json(asdict(event))),
        )

    # Record 1 trade consumption for R_75
    guard.consume("default", "R_75", at=now)

    # Assemble snapshots
    assembler = DigestAssembler(store, trade_guard=guard, account_scope="default")
    snapshots = assembler.build_snapshots((pair,), at=now)

    assert len(snapshots) == 1
    s = snapshots[0]
    assert s.symbol == "R_75"
    assert s.timeframe == "H1"
    assert s.conclusion == "BUY"
    assert s.quality_score == 82.0
    assert s.is_steady is True  # BUY + HIGH
    assert s.cap_count == 1
    assert s.cap_limit == 20

    # Pair with no evidence produces NO_TRADE fallback
    pair2 = WatchPair("FX VOL 20", Timeframe.H1)
    snapshots2 = assembler.build_snapshots((pair2,), at=now)
    assert len(snapshots2) == 1
    s2 = snapshots2[0]
    assert s2.symbol == "FX VOL 20"
    assert s2.conclusion == "NO_TRADE"
    assert s2.quality_score is None
    assert s2.is_steady is False
    assert s2.cap_count == 0

    # Verify formatting produces expected digest text
    digest = format_daily_digest([s, s2], as_of=now)
    assert "<b>DAILY MARKET &amp; WATCHLIST DIGEST</b>" in digest
    assert "<b>R_75 (H1)</b>" in digest
    assert "• Conclusion: BUY" in digest
    assert "• Steady / Worth Trading: YES (STEADY)" in digest
    assert "• Daily Cap Usage: 1/20" in digest
    assert "<b>FX VOL 20 (H1)</b>" in digest
    assert "• Conclusion: NO_TRADE" in digest
    assert "• Steady / Worth Trading: NO (UNSTEADY)" in digest


@pytest.mark.asyncio
async def test_digest_scheduling_durable_flag_prevents_double_send(tmp_path: Path) -> None:
    from monitoring.observation_daemon import DigestAssembler, ObservationDaemonStore

    store_path = tmp_path / "evidence.sqlite3"
    daemon_store = ObservationDaemonStore(store_path, "session-123")
    pair = WatchPair("R_75", Timeframe.H1)
    now = datetime(2026, 9, 17, 10, 0, 0, tzinfo=timezone.utc)

    mock_gateway = AsyncMock()
    mock_gateway.send_text = AsyncMock()
    service = TelegramDigestService(mock_gateway, AsyncMock())
    assembler = DigestAssembler(daemon_store, trade_guard=None, account_scope="default")

    config = DaemonConfig(
        watches=(pair,),
        evidence_path=store_path,
        close_grace_seconds=5.0,
        max_backoff_seconds=30.0,
        heartbeat_stale_cycles=2,
    )
    daemon = ObservationDaemon(
        config,
        MagicMock(),
        telegram_digest_service=service,
        digest_assembler=assembler,
    )

    # First cycle sends digest
    await daemon._maybe_send_digest(now)
    assert mock_gateway.send_text.await_count == 1
    assert daemon.store.digest_already_sent("2026-09-17") is True

    # Second cycle on same UTC day is suppressed
    await daemon._maybe_send_digest(now)
    assert mock_gateway.send_text.await_count == 1  # unchanged

    # Next UTC day triggers send again
    next_day = datetime(2026, 9, 18, 10, 0, 0, tzinfo=timezone.utc)
    await daemon._maybe_send_digest(next_day)
    assert mock_gateway.send_text.await_count == 2
    assert daemon.store.digest_already_sent("2026-09-18") is True
