"""Offline regression tests -- Step 3b MT5 composition audit.

All tests use deterministic in-memory stubs. No real MT5 terminal is
imported or contacted. The MT5 SDK is shimmed by conftest.py before
collection begins.

Scenarios covered
-----------------
1.  Competing owners: second gateway refused at reserve time.
2.  Stale handle after ownership transfer.
3.  Account login switch between identity pin and a later read.
4.  Server change between identity pin and a later read.
5a. Init failure: SDK init returns False -- session released.
5b. Init failure: identity pin unavailable (account_info None).
5c. Init failure: second identity cross-check conflicts.
6.  Exception during connect -- session fully released.
7.  Repeated disconnects -- idempotent, no double shutdown.
8.  Concurrent disconnects -- shutdown called exactly once.
9.  Telemetry read after external ownership loss -- rejected.
10. DEMO-value rejection matrix (all non-int(0) trade_mode values).
11. Runner/campaign composition: two MT5 gateways -- second refused.
12. Legacy disconnect() is a no-op for non-owners (REGRESSION GUARD).
13. Owner disconnect() cleans up session and SDK fully.
14. Portable observation gateway cannot bypass an active owner.
15. Shutdown failure still revokes session ownership.
16. get_positions() rejected without ownership.
17. get_trade_history() rejected without ownership.
18. _pinned_identity cleared on successful disconnect.
19. _pinned_identity cleared on failed connect.
20. Legacy connect+disconnect round-trip works end-to-end.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from broker.mt5_gateway import MT5Gateway
from core.exceptions import BrokerConnectionError
from core.mt5_session import mt5_session


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _account(*, login=101, server="Fake-Demo", trade_mode=0):
    return SimpleNamespace(
        login=login, server=server, trade_mode=trade_mode,
        balance=5000.0, equity=5000.0, currency="USD", leverage=200,
    )


def _wire(monkeypatch, *, login=101, server="Fake-Demo"):
    """Wire a clean offline SDK stub into the broker.mt5_gateway module."""
    sdk = SimpleNamespace(
        account_info=Mock(return_value=_account(login=login, server=server)),
        terminal_info=Mock(return_value=SimpleNamespace(connected=True)),
    )
    initialize = Mock(return_value=True)
    shutdown = Mock()
    monkeypatch.setattr("broker.mt5_gateway.mt5", sdk)
    monkeypatch.setattr("broker.mt5_gateway.mt5_connect", initialize)
    monkeypatch.setattr("broker.mt5_gateway.mt5_disconnect", shutdown)
    return sdk, initialize, shutdown


# ===========================================================================
# 1. Competing owners: second gateway refused at reserve time
# ===========================================================================

@pytest.mark.asyncio
async def test_second_gateway_refused_at_reserve(monkeypatch):
    _, init1, _ = _wire(monkeypatch)
    g1 = MT5Gateway(expected_environment="demo")
    g2 = MT5Gateway(expected_environment="demo")
    await g1.connect()
    assert g1.is_connected is True
    with pytest.raises(BrokerConnectionError, match="already owned"):
        await g2.connect()
    assert g2.is_connected is False
    init1.assert_called_once()
    await g1.disconnect()


# ===========================================================================
# 2. Stale handle after ownership transfer
# ===========================================================================

@pytest.mark.asyncio
async def test_stale_handle_rejected_after_ownership_transfer(monkeypatch):
    _wire(monkeypatch)
    g1 = MT5Gateway(expected_environment="demo")
    await g1.connect()
    await g1.disconnect()
    _wire(monkeypatch)
    g2 = MT5Gateway(expected_environment="demo")
    await g2.connect()
    with pytest.raises(BrokerConnectionError, match="not connected"):
        await g1.get_account_info()
    await g2.disconnect()


# ===========================================================================
# 3. Account login switch between pin and read
# ===========================================================================

@pytest.mark.asyncio
async def test_account_switch_between_pin_and_read_rejected(monkeypatch):
    sdk, _, shutdown = _wire(monkeypatch)
    gateway = MT5Gateway(expected_environment="demo")
    await gateway.connect()
    assert (await gateway.get_account_info()).account_id == "101"
    sdk.account_info.return_value = _account(login=999)
    with pytest.raises(BrokerConnectionError, match="pinned account"):
        await gateway.get_account_info()
    # On a runtime identity mismatch the gateway deactivates (session stays reserved)
    # but does NOT call mt5_disconnect -- that is reserved for connect-time failures.
    assert gateway.is_connected is False


# ===========================================================================
# 4. Server change between pin and read
# ===========================================================================

@pytest.mark.asyncio
async def test_server_change_between_pin_and_read_rejected(monkeypatch):
    sdk, _, _ = _wire(monkeypatch)
    gateway = MT5Gateway(expected_environment="demo")
    await gateway.connect()
    sdk.account_info.return_value = _account(login=101, server="DIFFERENT")
    with pytest.raises(BrokerConnectionError, match="pinned account"):
        await gateway.get_account_info()
    assert gateway.is_connected is False


# ===========================================================================
# 5a. SDK init returns False -- session released
# ===========================================================================

@pytest.mark.asyncio
async def test_sdk_init_failure_releases_session(monkeypatch):
    sdk = SimpleNamespace(account_info=Mock(), terminal_info=Mock())
    monkeypatch.setattr("broker.mt5_gateway.mt5", sdk)
    monkeypatch.setattr("broker.mt5_gateway.mt5_connect", Mock(return_value=False))
    monkeypatch.setattr("broker.mt5_gateway.mt5_disconnect", Mock())
    gateway = MT5Gateway()
    with pytest.raises(BrokerConnectionError):
        await gateway.connect()
    assert gateway.is_connected is False
    assert mt5_session.owns(gateway._session_owner) is False


# ===========================================================================
# 5b. account_info returns None during pin -- session released
# ===========================================================================

@pytest.mark.asyncio
async def test_identity_pin_failure_releases_session(monkeypatch):
    shutdown = Mock()
    sdk = SimpleNamespace(
        account_info=Mock(return_value=None),
        terminal_info=Mock(return_value=SimpleNamespace(connected=True)),
    )
    monkeypatch.setattr("broker.mt5_gateway.mt5", sdk)
    monkeypatch.setattr("broker.mt5_gateway.mt5_connect", Mock(return_value=True))
    monkeypatch.setattr("broker.mt5_gateway.mt5_disconnect", shutdown)
    gateway = MT5Gateway()
    with pytest.raises(BrokerConnectionError):
        await gateway.connect()
    assert gateway.is_connected is False
    assert mt5_session.owns(gateway._session_owner) is False
    shutdown.assert_called_once()


# ===========================================================================
# 5c. Second cross-check returns different login -- session released
# ===========================================================================

@pytest.mark.asyncio
async def test_second_crosscheck_conflict_releases_session(monkeypatch):
    """The second _verify_connection_identity() call must catch a login change.

    _connect_session call sequence:
      call 1 -- _verify_connection_identity() (pin=None, passes through)
      call 2 -- direct mt5.account_info() used to SET the pin
      call 3 -- _verify_connection_identity() compares against the pin

    Returning a different login on call 3 triggers the identity conflict.
    """
    shutdown = Mock()
    calls = [0]

    def unstable():
        calls[0] += 1
        # Return the same identity for calls 1 and 2 (pin is set from call 2).
        # Return a different identity on call 3 to trigger the conflict check.
        if calls[0] <= 2:
            return _account(login=101)
        return _account(login=999)

    sdk = SimpleNamespace(
        account_info=unstable,
        terminal_info=Mock(return_value=SimpleNamespace(connected=True)),
    )
    monkeypatch.setattr("broker.mt5_gateway.mt5", sdk)
    monkeypatch.setattr("broker.mt5_gateway.mt5_connect", Mock(return_value=True))
    monkeypatch.setattr("broker.mt5_gateway.mt5_disconnect", shutdown)
    gateway = MT5Gateway()
    with pytest.raises(BrokerConnectionError):
        await gateway.connect()
    assert gateway.is_connected is False
    assert mt5_session.owns(gateway._session_owner) is False
    shutdown.assert_called_once()


# ===========================================================================
# 6. Exception during connect -- session fully released
# ===========================================================================

@pytest.mark.asyncio
async def test_exception_during_connect_releases_session(monkeypatch):
    shutdown = Mock()
    monkeypatch.setattr("broker.mt5_gateway.mt5_disconnect", shutdown)
    monkeypatch.setattr(
        "broker.mt5_gateway.mt5_connect",
        Mock(side_effect=RuntimeError("boom")),
    )
    gateway = MT5Gateway()
    with pytest.raises(RuntimeError, match="boom"):
        await gateway.connect()
    assert gateway.is_connected is False
    assert mt5_session.owns(gateway._session_owner) is False


# ===========================================================================
# 7. Repeated disconnects -- idempotent
# ===========================================================================

@pytest.mark.asyncio
async def test_repeated_disconnect_idempotent(monkeypatch):
    _, _, shutdown = _wire(monkeypatch)
    gateway = MT5Gateway(expected_environment="demo")
    await gateway.connect()
    await gateway.disconnect()
    await gateway.disconnect()
    await gateway.disconnect()
    shutdown.assert_called_once()
    assert gateway.is_connected is False


# ===========================================================================
# 8. Concurrent disconnects -- shutdown called exactly once
# ===========================================================================

@pytest.mark.asyncio
async def test_concurrent_disconnects_shutdown_once(monkeypatch):
    _, _, shutdown = _wire(monkeypatch)
    gateway = MT5Gateway(expected_environment="demo")
    await gateway.connect()

    async def attempt():
        await gateway.disconnect()
        return gateway.is_connected

    results = await asyncio.gather(attempt(), attempt(), attempt())
    shutdown.assert_called_once()
    assert all(r is False for r in results)


# ===========================================================================
# 9. Telemetry read after external ownership loss
# ===========================================================================

@pytest.mark.asyncio
async def test_read_after_external_ownership_loss_rejected(monkeypatch):
    sdk, _, _ = _wire(monkeypatch)
    gateway = MT5Gateway(expected_environment="demo")
    await gateway.connect()
    sdk.account_info.reset_mock()
    mt5_session.invalidate()
    with pytest.raises(BrokerConnectionError, match="not connected"):
        await gateway.get_account_info()
    sdk.account_info.assert_not_called()


# ===========================================================================
# 10. DEMO-value rejection matrix -- every non-int(0) trade_mode refused
# ===========================================================================

@pytest.mark.asyncio
@pytest.mark.parametrize("bad_mode", [
    False, True, 0.0, 1.0, "0", "demo", "", None, {}, [],
    1, 2, 99, -1,
])
async def test_non_demo_trade_mode_refused_at_connect(monkeypatch, bad_mode):
    shutdown = Mock()
    sdk = SimpleNamespace(
        account_info=Mock(return_value=_account(trade_mode=bad_mode)),
        terminal_info=Mock(return_value=SimpleNamespace(connected=True)),
    )
    monkeypatch.setattr("broker.mt5_gateway.mt5", sdk)
    monkeypatch.setattr("broker.mt5_gateway.mt5_connect", Mock(return_value=True))
    monkeypatch.setattr("broker.mt5_gateway.mt5_disconnect", shutdown)
    gateway = MT5Gateway(expected_environment="demo")
    with pytest.raises(BrokerConnectionError):
        await gateway.connect()
    assert gateway.is_connected is False
    shutdown.assert_called_once()


# ===========================================================================
# 11. Runner/campaign: two MT5 gateways -- second refused
# ===========================================================================

@pytest.mark.asyncio
async def test_runner_second_gateway_refused(monkeypatch):
    _wire(monkeypatch)
    production = MT5Gateway(expected_environment="demo")
    observation = MT5Gateway(expected_environment="demo")
    await production.connect()
    with pytest.raises(BrokerConnectionError, match="already owned"):
        await observation.connect()
    assert observation.is_connected is False
    assert production.is_connected is True
    await production.disconnect()


# ===========================================================================
# 12. Legacy disconnect() is a no-op for non-owners (REGRESSION GUARD)
#
# Before the fix, disconnect() in core/mt5_connection.py called
# mt5.shutdown() and mt5_session.invalidate() unconditionally regardless of
# session ownership -- a defect that allowed any caller to rip the session
# from under an active gateway.
#
# After the fix, a non-owner disconnect() is silently ignored:
# - gateway.is_connected remains True
# - mt5.shutdown() is never called
# ===========================================================================

@pytest.mark.asyncio
async def test_legacy_disconnect_noop_for_non_owners(monkeypatch):
    _wire(monkeypatch)
    gateway = MT5Gateway(expected_environment="demo")
    await gateway.connect()

    raw_sdk = SimpleNamespace(shutdown=Mock())
    monkeypatch.setattr("core.mt5_connection.mt5", raw_sdk)

    from core.mt5_connection import disconnect as legacy_disconnect
    legacy_disconnect()  # non-owner -- must be a complete no-op

    assert gateway.is_connected is True, (
        "Gateway session must survive a non-owning legacy disconnect() call"
    )
    raw_sdk.shutdown.assert_not_called()

    await gateway.disconnect()
    assert gateway.is_connected is False


# ===========================================================================
# 13. Owner disconnect() cleans up session and SDK
# ===========================================================================

@pytest.mark.asyncio
async def test_owner_disconnect_cleans_session_and_sdk(monkeypatch):
    _, _, shutdown = _wire(monkeypatch)
    gateway = MT5Gateway(expected_environment="demo")
    await gateway.connect()
    assert mt5_session.owns(gateway._session_owner) is True
    await gateway.disconnect()
    assert gateway.is_connected is False
    assert mt5_session.owns(gateway._session_owner) is False
    shutdown.assert_called_once()


# ===========================================================================
# 14. Portable observation gateway cannot bypass an active owner
# ===========================================================================

@pytest.mark.asyncio
async def test_portable_observation_cannot_bypass_active_owner(monkeypatch, tmp_path):
    from broker.mt5_telemetry import _PortableObservationGateway
    _wire(monkeypatch)
    primary = MT5Gateway(expected_environment="demo")
    await primary.connect()
    raw_initialize = Mock(return_value=True)
    monkeypatch.setattr("broker.mt5_telemetry.mt5.initialize", raw_initialize)
    observation = _PortableObservationGateway(portable_data_path=tmp_path)
    with pytest.raises(BrokerConnectionError, match="already owned"):
        await observation.connect()
    raw_initialize.assert_not_called()
    assert primary.is_connected is True
    await primary.disconnect()


# ===========================================================================
# 15. Shutdown failure still revokes session
# ===========================================================================

@pytest.mark.asyncio
async def test_shutdown_failure_still_revokes_session(monkeypatch):
    _, _, shutdown = _wire(monkeypatch)
    shutdown.side_effect = RuntimeError("SDK shutdown failure")
    gateway = MT5Gateway(expected_environment="demo")
    await gateway.connect()
    with pytest.raises(RuntimeError, match="SDK shutdown failure"):
        await gateway.disconnect()
    assert gateway.is_connected is False
    assert mt5_session.owns(gateway._session_owner) is False


# ===========================================================================
# 16. get_positions() rejected without ownership
# ===========================================================================

@pytest.mark.asyncio
async def test_get_positions_rejected_when_not_connected(monkeypatch):
    _wire(monkeypatch)
    gateway = MT5Gateway(expected_environment="demo")
    with pytest.raises(BrokerConnectionError, match="not connected"):
        await gateway.get_positions()


# ===========================================================================
# 17. get_trade_history() rejected without ownership
# ===========================================================================

@pytest.mark.asyncio
async def test_get_trade_history_rejected_when_not_connected(monkeypatch):
    _wire(monkeypatch)
    gateway = MT5Gateway(expected_environment="demo")
    with pytest.raises(BrokerConnectionError, match="not connected"):
        await gateway.get_trade_history()


# ===========================================================================
# 18. _pinned_identity cleared on successful disconnect
# ===========================================================================

@pytest.mark.asyncio
async def test_pinned_identity_cleared_on_disconnect(monkeypatch):
    _wire(monkeypatch)
    gateway = MT5Gateway(expected_environment="demo")
    await gateway.connect()
    assert gateway._pinned_identity is not None
    await gateway.disconnect()
    assert gateway._pinned_identity is None


# ===========================================================================
# 19. _pinned_identity cleared on failed connect
# ===========================================================================

@pytest.mark.asyncio
async def test_pinned_identity_cleared_on_failed_connect(monkeypatch):
    """A failed connect must not leave a stale _pinned_identity behind.

    Uses the same call-sequence logic as test_second_crosscheck_conflict:
    conflict triggers on call 3 (the second verify_connection_identity).
    """
    calls = [0]
    shutdown = Mock()

    def unstable():
        calls[0] += 1
        if calls[0] <= 2:
            return _account(login=200)
        return _account(login=999)

    sdk = SimpleNamespace(
        account_info=unstable,
        terminal_info=Mock(return_value=SimpleNamespace(connected=True)),
    )
    monkeypatch.setattr("broker.mt5_gateway.mt5", sdk)
    monkeypatch.setattr("broker.mt5_gateway.mt5_connect", Mock(return_value=True))
    monkeypatch.setattr("broker.mt5_gateway.mt5_disconnect", shutdown)
    gateway = MT5Gateway()
    with pytest.raises(BrokerConnectionError):
        await gateway.connect()
    assert gateway._pinned_identity is None


# ===========================================================================
# 20. Legacy connect+disconnect round-trip works end-to-end
# ===========================================================================

@pytest.mark.asyncio
async def test_legacy_connect_disconnect_round_trip(monkeypatch):
    """The legacy owner token must still support a complete connect/disconnect cycle."""
    from core.mt5_connection import _LEGACY_SESSION_OWNER
    raw_sdk = SimpleNamespace(
        initialize=Mock(return_value=True),
        shutdown=Mock(),
    )
    monkeypatch.setattr("core.mt5_connection.mt5", raw_sdk)
    from core.mt5_connection import connect as legacy_connect, disconnect as legacy_disconnect
    result = legacy_connect()
    assert result is True
    assert mt5_session.is_active(_LEGACY_SESSION_OWNER) is True
    legacy_disconnect()
    assert mt5_session.owns(_LEGACY_SESSION_OWNER) is False
    raw_sdk.shutdown.assert_called_once()
