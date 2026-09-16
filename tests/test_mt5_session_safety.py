"""Offline regression coverage for MT5 identity and process-global ownership."""

import asyncio
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from broker.mt5_gateway import MT5Gateway
from core.exceptions import BrokerConnectionError
from core.mt5_session import mt5_session


def account(*, login=101, server="Fake-Demo", trade_mode=0):
    return SimpleNamespace(
        login=login, server=server, trade_mode=trade_mode,
        balance=1000.0, equity=1000.0, currency="USD", leverage=100,
    )


@pytest.fixture
def offline_sdk(monkeypatch):
    sdk = SimpleNamespace(
        account_info=Mock(return_value=account()),
        terminal_info=Mock(return_value=SimpleNamespace(connected=True)),
    )
    initialize = Mock(return_value=True)
    shutdown = Mock()
    monkeypatch.setattr("broker.mt5_gateway.mt5", sdk)
    monkeypatch.setattr("broker.mt5_gateway.mt5_connect", initialize)
    monkeypatch.setattr("broker.mt5_gateway.mt5_disconnect", shutdown)
    return sdk, initialize, shutdown


@pytest.mark.parametrize("changed", [account(login=202), account(server="Other-Demo")])
async def test_account_read_rejects_switched_pinned_identity(offline_sdk, changed):
    sdk, _, shutdown = offline_sdk
    gateway = MT5Gateway(expected_environment="demo")
    await gateway.connect()
    assert (await gateway.get_account_info()).account_id == "101"
    sdk.account_info.return_value = changed
    with pytest.raises(BrokerConnectionError, match="pinned account") as exc:
        await gateway.get_account_info()
    assert "101" not in str(exc.value) and "202" not in str(exc.value)
    assert gateway.is_connected is False
    await gateway.disconnect()
    shutdown.assert_called_once()


async def test_shared_shutdown_invalidates_owner_before_another_read(offline_sdk, monkeypatch):
    sdk, _, _ = offline_sdk
    gateway = MT5Gateway(expected_environment="demo")
    await gateway.connect()
    raw_sdk = SimpleNamespace(shutdown=Mock())
    monkeypatch.setattr("core.mt5_connection.mt5", raw_sdk)
    from core.mt5_connection import disconnect
    disconnect()
    assert gateway.is_connected is False
    sdk.account_info.reset_mock()
    with pytest.raises(BrokerConnectionError, match="not connected"):
        await gateway.get_account_info()
    sdk.account_info.assert_not_called()
    raw_sdk.shutdown.assert_called_once()


async def test_competing_owner_refuses_before_initialization(offline_sdk):
    _, initialize, shutdown = offline_sdk
    first, second = MT5Gateway(), MT5Gateway()
    await first.connect()
    with pytest.raises(BrokerConnectionError, match="already owned"):
        await second.connect()
    assert first.is_connected is True and second.is_connected is False
    initialize.assert_called_once()
    await second.disconnect()
    shutdown.assert_not_called()
    await first.disconnect()
    assert first.is_connected is False
    await second.connect()
    await first.disconnect()
    assert second.is_connected is True
    assert shutdown.call_count == 1
    await second.disconnect()


async def test_unavailable_account_invalidates_session_and_cleans_up(offline_sdk):
    sdk, _, shutdown = offline_sdk
    gateway = MT5Gateway()
    await gateway.connect()
    sdk.account_info.return_value = None
    with pytest.raises(BrokerConnectionError, match="retrieve MT5 account info"):
        await gateway.get_account_info()
    assert gateway.is_connected is False
    await gateway.disconnect()
    shutdown.assert_called_once()


@pytest.mark.parametrize("mode", [False, True, 0.0, 1, 2, 99, "0", "demo", None, {}, []])
async def test_malformed_or_non_demo_sdk_status_refuses(offline_sdk, mode):
    sdk, _, shutdown = offline_sdk
    sdk.account_info.return_value = account(trade_mode=mode)
    gateway = MT5Gateway(expected_environment="demo")
    with pytest.raises(BrokerConnectionError, match="identity verification failed"):
        await gateway.connect()
    assert gateway.is_connected is False
    shutdown.assert_called_once()


@pytest.mark.parametrize("result", [False, 0, 1, 0.0, 1.0, "true", None, {}, []])
async def test_connection_verification_requires_exact_boolean_true(offline_sdk, monkeypatch, result):
    _, _, shutdown = offline_sdk
    gateway = MT5Gateway()
    monkeypatch.setattr(gateway, "_verify_connection_identity", lambda: result)
    with pytest.raises(BrokerConnectionError, match="identity verification failed"):
        await gateway.connect()
    assert gateway.is_connected is False
    shutdown.assert_called_once()


@pytest.mark.parametrize("result", [False, 0, 1, "true", None])
async def test_account_read_verification_requires_exact_boolean_true(offline_sdk, monkeypatch, result):
    gateway = MT5Gateway()
    await gateway.connect()
    monkeypatch.setattr(gateway, "_verify_connection_identity", lambda: result)
    with pytest.raises(BrokerConnectionError, match="pinned account"):
        await gateway.get_account_info()
    assert gateway.is_connected is False
    await gateway.disconnect()


async def test_missing_status_refuses(offline_sdk):
    sdk, _, _ = offline_sdk
    info = account()
    del info.trade_mode
    sdk.account_info.return_value = info
    with pytest.raises(BrokerConnectionError):
        await MT5Gateway().connect()


async def test_identity_change_between_observations_refuses(offline_sdk):
    sdk, _, _ = offline_sdk
    gateway = MT5Gateway()
    await gateway.connect()
    sdk.account_info.side_effect = [account(), account(login=202)]
    with pytest.raises(BrokerConnectionError, match="pinned account"):
        await gateway.get_account_info()
    assert gateway.is_connected is False
    await gateway.disconnect()


async def test_shutdown_failure_still_revokes_session(offline_sdk):
    _, _, shutdown = offline_sdk
    gateway = MT5Gateway()
    await gateway.connect()
    shutdown.side_effect = RuntimeError("stub shutdown failure")
    with pytest.raises(RuntimeError, match="stub shutdown failure"):
        await gateway.disconnect()
    assert gateway.is_connected is False
    assert mt5_session.owns(gateway._session_owner) is False


async def test_legacy_initialization_cannot_bypass_owner(offline_sdk, monkeypatch):
    gateway = MT5Gateway()
    await gateway.connect()
    raw_sdk = SimpleNamespace(initialize=Mock(return_value=True))
    monkeypatch.setattr("core.mt5_connection.mt5", raw_sdk)
    from core.mt5_connection import connect
    assert connect() is False
    raw_sdk.initialize.assert_not_called()
    assert gateway.is_connected is True
    await gateway.disconnect()


async def test_portable_observation_cannot_bypass_owner(offline_sdk, monkeypatch, tmp_path):
    from broker.mt5_telemetry import _PortableObservationGateway
    first = MT5Gateway()
    await first.connect()
    initialize = Mock(return_value=True)
    monkeypatch.setattr("broker.mt5_telemetry.mt5.initialize", initialize)
    second = _PortableObservationGateway(portable_data_path=tmp_path)
    with pytest.raises(BrokerConnectionError, match="already owned"):
        await second.connect()
    initialize.assert_not_called()
    assert first.is_connected is True and second.is_connected is False
    await first.disconnect()


async def test_account_read_and_global_shutdown_are_serialized(offline_sdk, monkeypatch):
    sdk, _, _ = offline_sdk
    gateway = MT5Gateway()
    await gateway.connect()
    read_started, release_read, disconnect_started = Event(), Event(), Event()

    def paused_account():
        read_started.set()
        assert release_read.wait(5), "offline read was not released"
        return account()

    sdk.account_info.side_effect = paused_account
    raw_sdk = SimpleNamespace(shutdown=Mock())
    monkeypatch.setattr("core.mt5_connection.mt5", raw_sdk)
    from core.mt5_connection import disconnect

    def request_disconnect():
        disconnect_started.set()
        disconnect()

    read_task = asyncio.create_task(gateway.get_account_info())
    disconnect_task = None
    try:
        assert await asyncio.to_thread(read_started.wait, 5)
        disconnect_task = asyncio.create_task(asyncio.to_thread(request_disconnect))
        assert await asyncio.to_thread(disconnect_started.wait, 5)
        raw_sdk.shutdown.assert_not_called()
    finally:
        release_read.set()
        result = await read_task
        if disconnect_task is not None:
            await disconnect_task
    assert result.account_id == "101"
    assert gateway.is_connected is False
    raw_sdk.shutdown.assert_called_once()
