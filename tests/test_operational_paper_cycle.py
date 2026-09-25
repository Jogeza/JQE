from pathlib import Path

import pytest

from config.settings import settings
from tools.run_operational_paper_cycle import run


@pytest.mark.asyncio
async def test_operational_cycle_is_simulation_only_and_projects_outcome(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "broker_execution_enabled", False)
    monkeypatch.setattr(settings, "dashboard_paper_store_path", tmp_path / "paper.sqlite3")
    monkeypatch.setattr(settings, "dashboard_paper_intent_store_path", tmp_path / "intents.sqlite3")
    monkeypatch.setattr(settings, "simulation_daily_submission_store_path", tmp_path / "daily.sqlite3")
    monkeypatch.setattr(settings, "historical_data_path", tmp_path / "candles.sqlite3")
    result = await run()

    assert result["mode"] == "SIMULATION_ONLY"
    assert result["gateway_class"] == "SimulationGateway"
    assert result["gateway_account"] == "SIMULATED"
    assert result["broker_execution_enabled"] is False
    assert result["market_data"]["source"] == "SIMULATION"
    assert result["paper_outcome"]["paper_only"] is True
    assert result["api_projection"]["latest_paper_outcome"]["paper_only"] is True


def test_operational_cycle_has_no_broker_factory_or_live_gateway_import() -> None:
    source = Path("tools/run_operational_paper_cycle.py").read_text(encoding="utf-8")
    assert "broker.factory" not in source
    assert "MT5" not in source
    assert "Weltrade" not in source
    assert "Deriv" not in source
