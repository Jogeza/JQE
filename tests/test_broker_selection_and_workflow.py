"""Stage 6 broker-selection workflow tests.

Covers durable persistence, effective-broker resolution, the unresolved-intent
switching lock, availability validation for real brokers, the no-silent-
simulation-fallback invariant, DemoOnlyGuard enforcement, and API route
behavior for POST /api/v1/brokers/select.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from api.app import create_app
from api.dto import SelectBrokerRequest
from api.routes import get_broker_status as route_get_broker_status
from api.routes import select_broker as route_select_broker
from api.service import (
    ApplicationService,
    BrokerSwitchConflictError,
    BrokerUnavailableError,
)
from broker.factory import get_gateway
from broker.simulation_gateway import SimulationGateway
from config.settings import Settings, settings
from core.exceptions import ConfigurationError
from data.broker_selection import (
    BrokerSelectionStore,
    get_effective_broker,
    normalize_broker_name,
)
from execution.models import IntentRecord, IntentRecordStatus
from execution.persistence import SQLiteIntentRecordStore


@pytest.fixture(autouse=True)
def _isolated_intent_store(tmp_path, monkeypatch):
    """Keep switching-lock checks away from the real state/ intent store."""
    monkeypatch.setattr(settings, "intent_store_path", tmp_path / "intents.sqlite3")
    yield


def _make_deriv_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "deriv_api_token", "test-token")
    monkeypatch.setattr(settings, "deriv_options_account_id", "VRTC123456")
    monkeypatch.setattr(settings, "deriv_expected_environment", "demo")


def _make_weltrade_available(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    terminal = tmp_path / "weltrade-terminal64.exe"
    terminal.touch()
    monkeypatch.setattr(settings, "weltrade_terminal_path", terminal)
    monkeypatch.setattr(settings, "weltrade_demo_login", 4242)
    monkeypatch.setattr(settings, "weltrade_demo_server", "Weltrade-Demo")


def _seed_unresolved_intent(status: IntentRecordStatus = IntentRecordStatus.PENDING) -> None:
    store = SQLiteIntentRecordStore(settings.intent_store_path)
    store.try_claim(IntentRecord("intent-key-1", status))


# --- Durable store -----------------------------------------------------------


def test_selection_persists_across_store_instances(tmp_path: Path) -> None:
    path = tmp_path / "broker_selection.sqlite3"
    store = BrokerSelectionStore(path)
    assert store.get_selected_broker() is None

    canonical = store.set_selected_broker("Weltrade_Demo", reason="operator test")
    assert canonical == "weltrade"

    reopened = BrokerSelectionStore(path)
    assert reopened.get_selected_broker() == "weltrade"


@pytest.mark.parametrize(
    ("raw", "canonical"),
    [
        ("mt5", "mt5"),
        ("MT5", "mt5"),
        ("mt5_demo", "mt5"),
        ("weltrade", "weltrade"),
        ("Weltrade_Demo", "weltrade"),
        ("deriv", "deriv"),
        ("DERIV_demo", "deriv"),
        ("simulation", "simulation"),
        (" Simulation ", "simulation"),
    ],
)
def test_broker_name_normalization(raw: str, canonical: str) -> None:
    assert normalize_broker_name(raw) == canonical


def test_normalization_rejects_unknown_broker() -> None:
    with pytest.raises(ConfigurationError, match="Unsupported broker"):
        normalize_broker_name("binance")


@pytest.mark.parametrize("broker", ["mt5", "weltrade", "deriv", "simulation"])
def test_store_roundtrips_every_supported_broker(tmp_path: Path, broker: str) -> None:
    path = tmp_path / "selection.sqlite3"
    store = BrokerSelectionStore(path)
    store.set_selected_broker(broker)
    assert BrokerSelectionStore(path).get_selected_broker() == broker


# --- Effective broker resolution ----------------------------------------------


def test_default_resolution_is_mt5(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JQE_BROKER", raising=False)
    fresh = Settings(_env_file=None)
    assert get_effective_broker(fresh) == "mt5"
    assert fresh.effective_broker == "mt5"


def test_configured_broker_used_when_no_persisted_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fresh = Settings(_env_file=None, broker="deriv")
    assert get_effective_broker(fresh) == "deriv"


def test_explicit_simulation_configuration_is_honored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("JQE_BROKER", raising=False)
    fresh = Settings(_env_file=None, broker="simulation")
    assert get_effective_broker(fresh) == "simulation"


def test_never_silently_defaults_to_simulation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("JQE_BROKER", raising=False)
    fresh = Settings(_env_file=None)
    assert fresh.effective_broker != "simulation"


def test_persisted_selection_overrides_configured_broker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store_path = tmp_path / "selection.sqlite3"
    monkeypatch.setattr(settings, "broker_selection_store_path", store_path)
    monkeypatch.setattr(settings, "broker", "deriv")
    BrokerSelectionStore(store_path).set_selected_broker("weltrade")
    assert settings.effective_broker == "weltrade"


def test_unsupported_configured_broker_fails_clearly() -> None:
    fresh = Settings(_env_file=None)
    fresh.broker = "unsupported"
    with pytest.raises(ConfigurationError, match="Unsupported broker"):
        get_effective_broker(fresh)


def test_factory_uses_persisted_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store_path = tmp_path / "selection.sqlite3"
    monkeypatch.setattr(settings, "broker_selection_store_path", store_path)
    monkeypatch.setattr(settings, "broker", "mt5")
    BrokerSelectionStore(store_path).set_selected_broker("simulation")
    assert isinstance(get_gateway(settings), SimulationGateway)


def test_factory_never_falls_back_to_simulation_for_misconfigured_deriv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store_path = tmp_path / "selection.sqlite3"
    monkeypatch.setattr(settings, "broker_selection_store_path", store_path)
    monkeypatch.setattr(settings, "deriv_api_token", None)
    BrokerSelectionStore(store_path).set_selected_broker("deriv")
    with pytest.raises(ConfigurationError):
        get_gateway(settings)


# --- Service: select_broker -----------------------------------------------------


@pytest.mark.parametrize("broker", ["mt5", "weltrade", "deriv", "simulation"])
def test_select_broker_persists_every_supported_broker(
    broker: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_deriv_available(monkeypatch)
    _make_weltrade_available(monkeypatch, tmp_path)
    monkeypatch.setattr(settings, "mt5_expected_environment", "demo")

    service = ApplicationService()
    response = service.select_broker(broker, reason="stage-6 test")

    assert response.selected_broker == broker
    assert response.persisted is True
    assert response.status.active_broker == broker
    assert settings.effective_broker == broker
    persisted = BrokerSelectionStore(settings.broker_selection_store_path)
    assert persisted.get_selected_broker() == broker


def test_select_broker_blocked_by_unresolved_pending_intent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_unresolved_intent(IntentRecordStatus.PENDING)
    service = ApplicationService()

    with pytest.raises(BrokerSwitchConflictError, match="unresolved"):
        service.select_broker("simulation")

    persisted = BrokerSelectionStore(settings.broker_selection_store_path)
    assert persisted.get_selected_broker() is None

    status = service.get_broker_status()
    assert status.can_switch is False
    assert status.unresolved_intent_count == 1
    assert "unresolved" in (status.switch_blocked_reason or "").lower()
    for item in status.brokers:
        assert item.can_switch is False
        if not item.is_active:
            assert item.switch_blocked_reason is not None


def test_select_broker_blocked_by_unknown_intent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_unresolved_intent(IntentRecordStatus.UNKNOWN)
    service = ApplicationService()
    with pytest.raises(BrokerSwitchConflictError):
        service.select_broker("mt5")


def test_select_broker_allowed_after_intents_resolved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_unresolved_intent(IntentRecordStatus.PENDING)
    store = SQLiteIntentRecordStore(settings.intent_store_path)
    store.transition(IntentRecord("intent-key-1", IntentRecordStatus.REJECTED))

    service = ApplicationService()
    response = service.select_broker("simulation")
    assert response.selected_broker == "simulation"


def test_select_unavailable_deriv_fails_without_simulation_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "deriv_api_token", None)
    monkeypatch.setattr(settings, "deriv_options_account_id", None)
    monkeypatch.setattr(settings, "broker", "mt5")
    service = ApplicationService()

    with pytest.raises(BrokerUnavailableError, match="JQE_DERIV_API_TOKEN"):
        service.select_broker("deriv")

    persisted = BrokerSelectionStore(settings.broker_selection_store_path)
    assert persisted.get_selected_broker() is None
    assert settings.effective_broker == "mt5"


def test_select_deriv_requires_demo_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_deriv_available(monkeypatch)
    monkeypatch.setattr(settings, "deriv_expected_environment", "real")
    service = ApplicationService()
    with pytest.raises(BrokerUnavailableError, match="demo"):
        service.select_broker("deriv")


def test_select_mt5_rejects_live_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "mt5_expected_environment", "live")
    service = ApplicationService()
    with pytest.raises(BrokerUnavailableError, match="prohibited"):
        service.select_broker("mt5")


def test_select_weltrade_requires_terminal_and_demo_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "weltrade_terminal_path", None)
    monkeypatch.setattr(settings, "weltrade_demo_login", None)
    monkeypatch.setattr(settings, "weltrade_login", None)
    service = ApplicationService()
    with pytest.raises(BrokerUnavailableError, match="Weltrade"):
        service.select_broker("weltrade")


def test_select_simulation_is_always_available_as_explicit_choice() -> None:
    service = ApplicationService()
    response = service.select_broker("simulation", reason="development/testing")
    assert response.selected_broker == "simulation"
    assert settings.effective_broker == "simulation"


# --- Broker status switching gates ----------------------------------------------


def test_status_marks_switchability_per_broker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_deriv_available(monkeypatch)
    monkeypatch.setattr(settings, "mt5_expected_environment", "demo")
    monkeypatch.setattr(settings, "weltrade_terminal_path", None)
    monkeypatch.setattr(settings, "weltrade_demo_login", None)
    monkeypatch.setattr(settings, "weltrade_login", None)
    monkeypatch.setattr(settings, "broker", "mt5")

    status = ApplicationService().get_broker_status()
    assert status.can_switch is True
    assert status.switch_blocked_reason is None

    by_key = {item.broker: item for item in status.brokers}
    assert by_key["mt5"].is_active is True
    assert by_key["mt5"].can_switch is False
    assert by_key["deriv"].is_configured is True
    assert by_key["deriv"].is_available is True
    assert by_key["deriv"].can_switch is True
    assert by_key["weltrade"].is_configured is False
    assert by_key["weltrade"].is_available is False
    assert by_key["weltrade"].can_switch is False
    assert "WELTRADE_TERMINAL_PATH" in (by_key["weltrade"].error_message or "")
    assert by_key["simulation"].is_available is True
    assert by_key["simulation"].can_switch is True


# --- API route behavior -----------------------------------------------------------


def test_select_route_persists_and_returns_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = ApplicationService()
    response = route_select_broker(
        request=SelectBrokerRequest(broker="Simulation", reason="dev"),
        service=service,
    )
    assert response.selected_broker == "simulation"
    assert response.status.active_broker == "simulation"


def test_select_route_maps_conflict_to_409() -> None:
    _seed_unresolved_intent(IntentRecordStatus.PENDING)
    service = ApplicationService()
    with pytest.raises(HTTPException) as excinfo:
        route_select_broker(
            request=SelectBrokerRequest(broker="simulation"), service=service
        )
    assert excinfo.value.status_code == 409
    assert "unresolved" in str(excinfo.value.detail).lower()


def test_select_route_maps_unavailable_broker_to_400(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "deriv_api_token", None)
    service = ApplicationService()
    with pytest.raises(HTTPException) as excinfo:
        route_select_broker(request=SelectBrokerRequest(broker="deriv"), service=service)
    assert excinfo.value.status_code == 400
    assert "JQE_DERIV_API_TOKEN" in str(excinfo.value.detail)


def test_select_route_maps_unknown_broker_to_400() -> None:
    service = ApplicationService()
    with pytest.raises(HTTPException) as excinfo:
        route_select_broker(
            request=SelectBrokerRequest(broker="binance"), service=service
        )
    assert excinfo.value.status_code == 400
    assert "Unsupported broker" in str(excinfo.value.detail)


def test_select_route_registered_in_openapi() -> None:
    app = create_app()
    paths = app.openapi()["paths"]
    assert "/api/v1/brokers/select" in paths
    assert "post" in paths["/api/v1/brokers/select"]
    assert route_get_broker_status(service=ApplicationService()).can_switch in (True, False)
