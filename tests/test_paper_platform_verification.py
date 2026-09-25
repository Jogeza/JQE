from pathlib import Path

import pytest

from config.settings import settings
from tools.verify_paper_platform import verify


@pytest.mark.asyncio
async def test_fixture_passes_unchanged_gates_and_is_restart_idempotent(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "broker_execution_enabled", False)
    result = await verify(tmp_path / "isolated")

    assert result["fixture"]["signal_overridden"] is False
    assert result["decisions"]["signal"]["signal"] == "BUY"
    assert result["decisions"]["signal"]["confidence"] >= 75
    assert result["decisions"]["risk"]["status"] == "AUTHORIZED"
    assert result["decisions"]["policy"]["status"] == "AUTHORIZED"
    assert result["open"]["status"] == "OPENED"
    assert result["close"]["status"] == "CLOSED"
    assert result["close"]["close_reason"] == "TAKE_PROFIT"
    assert result["duplicates"]["outcome_rows"] == 1
    assert result["duplicates"]["intent_rows"] == 1
    assert result["duplicates"]["open_positions_after_close"] == 0
    assert result["duplicates"]["close_id_unchanged"] is True
    assert result["simulation_slots"]["broker_account_slots_consumed"] == 0
    assert result["monitoring_api"]["latest_paper_outcome"]["status"] == "CLOSED"


def test_supported_runtime_normal_source_is_not_the_fixture() -> None:
    source = Path("tools/paper_runtime.py").read_text(encoding="utf-8")
    run_section = source[source.index("async def run") :]
    assert "build_observation_source(source)" in run_section
    assert "_offline_observations" not in run_section
    assert "settings.paper_runtime_intent_store_path" in run_section
    factory = source[
        source.index("def build_observation_source") : source.index("async def evaluate_production_decision")
    ]
    assert "_offline_observations" not in factory
    assert "SimulationObservationSource()" in factory
