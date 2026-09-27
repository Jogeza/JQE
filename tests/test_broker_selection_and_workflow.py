"""Weltrade selection persistence, fail-closed migration and API safety gates."""
import inspect
import sqlite3
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from api.app import create_app
from api.dto import SelectBrokerRequest
from api.routes import select_broker as route_select_broker
from api.routes import get_broker_status as route_get_broker_status
from api.service import ApplicationService, BrokerSwitchConflictError, BrokerUnavailableError
from broker.factory import get_gateway
from broker.weltrade_gateway import WeltradeGateway
from config.settings import Settings, settings
from core.exceptions import ConfigurationError
from data.broker_selection import BrokerSelectionStore, get_effective_broker, normalize_broker_name
from execution.models import IntentRecord, IntentRecordStatus
from execution.persistence import SQLiteIntentRecordStore


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'intent_store_path', tmp_path / 'intents.sqlite3')
    monkeypatch.setattr(settings, 'broker', 'weltrade')
    terminal = tmp_path / 'terminal64.exe'
    terminal.touch()
    monkeypatch.setattr(settings, 'weltrade_terminal_path', terminal)
    monkeypatch.setattr(settings, 'weltrade_demo_login', 4242)
    monkeypatch.setattr(settings, 'weltrade_demo_server', 'Weltrade-Demo')
    monkeypatch.setattr(settings, 'weltrade_demo_password', 'fixture')


@pytest.mark.parametrize('raw', ['weltrade', 'WELTRADE', ' Weltrade_Demo '])
def test_normalization_and_persistence(raw, tmp_path):
    store = BrokerSelectionStore(tmp_path / 'selection.sqlite3')
    assert store.get_selected_broker() is None
    assert normalize_broker_name(raw) == 'weltrade'
    assert store.set_selected_broker(raw) == 'weltrade'
    assert BrokerSelectionStore(store.path).get_selected_broker() == 'weltrade'


@pytest.mark.parametrize('broker', ['mt5', 'mt5_demo', 'deriv', 'deriv_demo', 'simulation', 'unknown'])
def test_unsupported_selection_does_not_persist(broker):
    with pytest.raises(ConfigurationError, match='Unsupported broker'):
        ApplicationService().select_broker(broker)
    assert BrokerSelectionStore(settings.broker_selection_store_path).get_selected_broker() is None


def test_stale_persisted_broker_fails_closed():
    store = BrokerSelectionStore(settings.broker_selection_store_path)
    with sqlite3.connect(store.path) as conn:
        conn.execute("INSERT INTO broker_selection VALUES (1, 'deriv', 'old', 'legacy')")
    with pytest.raises(ConfigurationError, match='Unsupported broker'):
        get_effective_broker(settings)


def test_factory_uses_validated_persisted_weltrade():
    BrokerSelectionStore(settings.broker_selection_store_path).set_selected_broker('weltrade_demo')
    assert isinstance(get_gateway(settings), WeltradeGateway)


def test_unreadable_persisted_selection_fails_closed():
    settings.broker_selection_store_path.write_bytes(b'not a sqlite database')
    with pytest.raises(ConfigurationError, match='could not be read'):
        get_effective_broker(settings)


def test_directory_at_authoritative_selection_path_fails_closed(tmp_path, monkeypatch):
    directory = tmp_path / 'selection.sqlite3'
    directory.mkdir()
    monkeypatch.setattr(settings, 'broker_selection_store_path', directory)
    with pytest.raises(ConfigurationError, match='not a file'):
        get_effective_broker(settings)


def test_selection_reports_only_weltrade():
    response = ApplicationService().select_broker('weltrade_demo')
    assert response.persisted is True
    assert response.selected_broker == 'weltrade'
    assert [item.broker for item in response.status.brokers] == ['weltrade']


@pytest.mark.parametrize('state', [IntentRecordStatus.PENDING, IntentRecordStatus.UNKNOWN])
def test_unresolved_intents_block_selection(state):
    SQLiteIntentRecordStore(settings.intent_store_path).try_claim(IntentRecord('key', state))
    with pytest.raises(BrokerSwitchConflictError):
        ApplicationService().select_broker('weltrade')
    assert BrokerSelectionStore(settings.broker_selection_store_path).get_selected_broker() is None
    response = ApplicationService().get_broker_status()
    assert response.can_switch is False
    assert response.unresolved_intent_count == 1


def test_selection_allowed_after_terminal_resolution():
    store = SQLiteIntentRecordStore(settings.intent_store_path)
    store.try_claim(IntentRecord('key', IntentRecordStatus.PENDING))
    store.transition(IntentRecord('key', IntentRecordStatus.REJECTED))
    assert ApplicationService().select_broker('weltrade').persisted


def test_missing_terminal_is_unavailable_without_fallback(monkeypatch):
    monkeypatch.setattr(settings, 'weltrade_terminal_path', None)
    with pytest.raises(BrokerUnavailableError, match='Weltrade'):
        ApplicationService().select_broker('weltrade')
    assert BrokerSelectionStore(settings.broker_selection_store_path).get_selected_broker() is None


def test_missing_password_is_unavailable_and_not_persisted(monkeypatch):
    monkeypatch.setattr(settings, 'weltrade_demo_password', None)
    monkeypatch.setattr(settings, 'weltrade_password', None)
    status = ApplicationService().get_broker_status()
    item = status.brokers[0]
    assert item.is_configured is False
    assert item.is_available is False
    assert 'JQE_WELTRADE_DEMO_PASSWORD' in (item.error_message or '')
    with pytest.raises(BrokerUnavailableError, match='JQE_WELTRADE_DEMO_PASSWORD'):
        ApplicationService().select_broker('weltrade')
    assert BrokerSelectionStore(settings.broker_selection_store_path).get_selected_broker() is None


@pytest.mark.parametrize('broker', ['deriv', 'simulation', 'mt5', 'unknown'])
def test_select_route_rejects_unsupported_brokers(broker):
    with pytest.raises(HTTPException) as error:
        route_select_broker(request=SelectBrokerRequest(broker=broker), service=ApplicationService())
    assert error.value.status_code == 400


def test_route_conflict_is_409():
    SQLiteIntentRecordStore(settings.intent_store_path).try_claim(IntentRecord('key', IntentRecordStatus.UNKNOWN))
    with pytest.raises(HTTPException) as error:
        route_select_broker(request=SelectBrokerRequest(broker='weltrade'), service=ApplicationService())
    assert error.value.status_code == 409


def test_routes_registered():
    assert 'post' in create_app().openapi()['paths']['/api/v1/brokers/select']
    assert inspect.iscoroutinefunction(route_get_broker_status)
