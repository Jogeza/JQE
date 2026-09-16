"""Offline regression coverage for MT5 identity and process-global ownership."""

import asyncio
from threading import Event, Thread
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


async def test_non_owning_disconnect_is_a_noop(offline_sdk, monkeypatch):
    """Legacy disconnect() must NOT revoke a session owned by a gateway.

    Before the fix, disconnect() unconditionally called mt5.shutdown() and
    mt5_session.invalidate() regardless of ownership — a security defect that
    allowed any caller to rip the session out from under an active gateway.

    After the fix, a non-owner disconnect() call is silently ignored: the
    gateway session stays active and mt5.shutdown() is never called.
    """
    sdk, _, _ = offline_sdk
    gateway = MT5Gateway(expected_environment="demo")
    await gateway.connect()
    raw_sdk = SimpleNamespace(shutdown=Mock())
    monkeypatch.setattr("core.mt5_connection.mt5", raw_sdk)
    from core.mt5_connection import disconnect
    disconnect()  # non-owner — must be a no-op
    assert gateway.is_connected is True, "gateway session must survive a non-owning disconnect"
    raw_sdk.shutdown.assert_not_called()
    # Gateway's own disconnect still works correctly.
    await gateway.disconnect()
    assert gateway.is_connected is False


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


async def test_account_read_completes_and_non_owner_disconnect_is_noop(offline_sdk, monkeypatch):
    """A non-owning legacy disconnect() must not interrupt an in-progress read.

    Before the fix, calling disconnect() from a non-owner would race to
    invalidate the session after the read completed. After the fix, the
    non-owner call is silently ignored: the read completes successfully
    and the gateway session remains active.
    """
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
        disconnect()  # non-owner -- must be a no-op

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
    # Non-owner disconnect is a no-op: gateway stays up, shutdown never called.
    assert gateway.is_connected is True
    raw_sdk.shutdown.assert_not_called()
    await gateway.disconnect()


def test_session_authority_release_validates_owner_and_clears_only_after_shutdown():
    """mt5_session.release() must reject non-owners without calling shutdown,

    and only clear session ownership after shutdown completes.
    """
    mt5_session.invalidate()
    owner_a = object()
    non_owner = object()

    # 1. Unowned session: non-owner release returns False, callback not invoked.
    unowned_shutdown = Mock()
    assert mt5_session.release(non_owner, shutdown_callback=unowned_shutdown) is False
    unowned_shutdown.assert_not_called()

    # 2. Owned session: non-owner release returns False, callback not invoked, owner retained.
    assert mt5_session.reserve(owner_a) is True
    mt5_session.activate(owner_a)

    wrong_owner_shutdown = Mock()
    assert mt5_session.release(non_owner, shutdown_callback=wrong_owner_shutdown) is False
    wrong_owner_shutdown.assert_not_called()
    assert mt5_session.owns(owner_a) is True
    assert mt5_session.is_active(owner_a) is True

    # 3. Valid owner: callback invoked, ownership retained during callback, cleared after.
    owner_during_callback = None

    def callback():
        nonlocal owner_during_callback
        owner_during_callback = mt5_session._owner

    assert mt5_session.release(owner_a, shutdown_callback=callback) is True
    assert owner_during_callback is owner_a, "owner must not be cleared before shutdown callback completes"
    assert mt5_session.owns(owner_a) is False
    assert mt5_session._owner is None


def test_new_owner_cannot_acquire_authority_until_shutdown_and_invalidation_finish():
    """Deterministic race test using thread events (no timing or sleeps).

    Verifies that while an existing owner is executing its shutdown callback
    inside release(), a competing thread attempting to reserve the session
    is blocked on the authority lock and cannot acquire ownership until shutdown
    and invalidation have completely finished.
    """
    mt5_session.invalidate()
    owner_a = object()
    owner_b = object()

    assert mt5_session.reserve(owner_a) is True
    mt5_session.activate(owner_a)

    shutdown_entered = Event()
    release_shutdown = Event()
    shutdown_finished = Event()
    reserve_attempted = Event()
    owner_b_acquired = Event()

    def shutdown_callback():
        shutdown_entered.set()
        # Thread A holds mt5_session.lock while executing this callback.
        # Wait for main thread to confirm Thread B has attempted to reserve.
        assert release_shutdown.wait(timeout=5), "release_shutdown was not signalled"
        # Confirm while still inside shutdown callback under the lock:
        # 1. New owner has NOT acquired authority.
        assert not owner_b_acquired.is_set(), "new owner acquired authority while shutdown was executing"
        # 2. Existing ownership has NOT yet been cleared.
        assert mt5_session._owner is owner_a, "ownership was cleared before shutdown finished"

    def thread_a_worker():
        result = mt5_session.release(owner_a, shutdown_callback=shutdown_callback)
        assert result is True
        shutdown_finished.set()

    def thread_b_worker():
        reserve_attempted.set()
        # This call must block on mt5_session.lock until Thread A finishes release()
        acquired = mt5_session.reserve(owner_b)
        if acquired:
            owner_b_acquired.set()
            # Deterministically verify that shutdown and invalidation already finished
            assert shutdown_finished.is_set(), "authority acquired before shutdown completed"

    thread_a = Thread(target=thread_a_worker, name="releasing-owner-a")
    thread_b = Thread(target=thread_b_worker, name="acquiring-owner-b")

    try:
        thread_a.start()
        # Wait for Thread A to acquire lock and enter shutdown callback
        assert shutdown_entered.wait(timeout=5), "Thread A did not enter shutdown callback"

        thread_b.start()
        # Wait for Thread B to begin reserve() call
        assert reserve_attempted.wait(timeout=5), "Thread B did not attempt reserve"

        # At this barrier point, Thread B has reached reserve(owner_b) and is blocked on mt5_session.lock.
        # Deterministically verify:
        assert not owner_b_acquired.is_set(), "Owner B acquired prematurely"
        assert not shutdown_finished.is_set(), "Shutdown finished prematurely"
        assert mt5_session._owner is owner_a, "Owner A is not current owner"

        # Unblock Thread A to complete shutdown callback and clear session state
        release_shutdown.set()

        # Thread B must now acquire the session
        assert owner_b_acquired.wait(timeout=5), "Owner B was not acquired after shutdown"

        thread_a.join(timeout=5)
        thread_b.join(timeout=5)

        assert not thread_a.is_alive()
        assert not thread_b.is_alive()
        assert shutdown_finished.is_set()
        assert mt5_session.owns(owner_b) is True
    finally:
        release_shutdown.set()
        thread_a.join(timeout=1)
        thread_b.join(timeout=1)
        mt5_session.invalidate()
