"""Truthful read-only monitoring telemetry for offline simulation."""

from datetime import datetime, timedelta, timezone

from api.service import ApplicationService
from config.settings import settings
from execution.dashboard_paper import DashboardPaperStore
from execution.market_setup import (
    DataFreshnessDTO, HistoricalWinRateDTO, MarketSetup, SetupAuthorizationDTO,
)


def test_expired_cached_setup_cannot_appear_live(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "dashboard_paper_store_path", tmp_path / "paper.sqlite3")
    monkeypatch.setattr(settings, "simulation_daily_submission_store_path", tmp_path / "daily.sqlite3")
    old = datetime.now(timezone.utc) - timedelta(hours=4)
    setup = MarketSetup(
        setup_id="old-setup", symbol="R_75", timeframe="H1", observed_at=old,
        candle_close_time=old, expires_at=old + timedelta(hours=2),
        direction="BUY", setup_state="READY", entry_price="100", stop_loss="99",
        targets=["102"], analyzed_candle_time=old - timedelta(hours=1),
        confidence_score=90, confidence_method="TEST", market_regime="TRENDING",
        data_freshness=DataFreshnessDTO(
            status="CACHED", source="SIMULATION", age_seconds=0,
            maximum_age_seconds=7200, reason="cached", freshness_state="FRESH",
            freshness_reason_codes=["CACHE_ONLY"], reason_codes=["CACHE_ONLY"],
        ),
        risk_authorization=SetupAuthorizationDTO(status="AUTHORIZED", reason="ok"),
        execution_authorization=SetupAuthorizationDTO(status="AUTHORIZED", reason="ok"),
        historical_win_rate=HistoricalWinRateDTO(),
    )
    DashboardPaperStore(settings.dashboard_paper_store_path).save_setup(setup)

    telemetry = ApplicationService().get_offline_monitoring()

    assert telemetry.backend.state == "LIVE"
    assert telemetry.candle_freshness.state == "STALE"
    assert telemetry.strategy.state == "STALE"
    assert telemetry.risk.state == "STALE"
    assert telemetry.execution_authorization.state == "STALE"
    assert "SETUP_EXPIRED" in telemetry.candle_freshness.reason_codes
    assert telemetry.broker_execution_enabled is False


def test_offline_monitoring_never_selects_a_broker(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "dashboard_paper_store_path", tmp_path / "paper.sqlite3")
    monkeypatch.setattr(settings, "simulation_daily_submission_store_path", tmp_path / "daily.sqlite3")
    service = ApplicationService()
    monkeypatch.setattr(service, "_get_gateway", lambda: (_ for _ in ()).throw(AssertionError("broker reached")))
    telemetry = service.get_offline_monitoring()
    assert telemetry.mode == "OFFLINE_SIMULATION"
    assert telemetry.broker_execution_enabled is False
    assert telemetry.open_paper_positions == 0
    assert telemetry.latest_paper_outcome is None
    assert telemetry.research_status is not None
    assert telemetry.research_status["status"] == "NO_DEMONSTRATED_POSITIVE_EDGE"
