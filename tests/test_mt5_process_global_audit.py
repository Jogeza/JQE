"""Offline audit tests: neither the real SDK nor a real gateway is imported."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest


@pytest.fixture
def audit(monkeypatch, tmp_path):
    sdk = ModuleType("MetaTrader5")
    sdk.initialize = Mock(return_value=True)
    sdk.terminal_info = Mock(return_value=SimpleNamespace(path="fake-terminal", data_path="fake-data"))
    sdk.account_info = Mock(side_effect=[
        SimpleNamespace(login=101, trade_mode=0),
        SimpleNamespace(login=202, trade_mode=0),
    ])
    gateway = SimpleNamespace(
        is_connected=True,
        connect=AsyncMock(),
        disconnect=AsyncMock(),
        get_account_info=AsyncMock(side_effect=[
            SimpleNamespace(account_id="101", trade_mode="demo"),
            SimpleNamespace(account_id="202", trade_mode="demo"),
        ]),
    )
    broker_module = ModuleType("broker.mt5_gateway")
    broker_module.MT5Gateway = Mock(return_value=gateway)
    monkeypatch.setitem(sys.modules, "MetaTrader5", sdk)
    monkeypatch.setitem(sys.modules, "broker.mt5_gateway", broker_module)
    source = Path(__file__).resolve().parents[1] / "tools" / "mt5_process_global_audit.py"
    spec = importlib.util.spec_from_file_location("offline_mt5_audit", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    terminal = tmp_path / "fake-terminal.exe"
    terminal.touch()
    monkeypatch.setattr(module, "DERIV_TERMINAL", terminal)
    monkeypatch.setattr(module, "WELTRADE_TERMINAL", terminal)
    monkeypatch.setenv("JQE_RUN_MT5_PROCESS_GLOBAL_AUDIT", "1")
    return module, sdk, gateway, broker_module.MT5Gateway


INVALID_ACCOUNTS = [
    pytest.param(SimpleNamespace(login=909090, trade_mode=2), id="live"),
    pytest.param(SimpleNamespace(login=909090, trade_mode=1), id="contest"),
    pytest.param(SimpleNamespace(login=909090, trade_mode=99), id="unknown"),
    pytest.param(None, id="missing-account"),
    pytest.param(SimpleNamespace(login=909090), id="missing-mode"),
    pytest.param(SimpleNamespace(login=909090, trade_mode=None), id="null-mode"),
    pytest.param(SimpleNamespace(login=909090, trade_mode="0"), id="string-mode"),
    pytest.param(SimpleNamespace(login=909090, trade_mode=False), id="boolean-mode"),
    pytest.param(SimpleNamespace(login=909090, trade_mode=0.0), id="float-mode"),
    pytest.param(SimpleNamespace(trade_mode=0), id="missing-identity"),
    pytest.param(SimpleNamespace(login="909090", trade_mode=0), id="malformed-identity"),
]


@pytest.mark.parametrize("session", [0, 1], ids=["first", "second"])
@pytest.mark.parametrize("invalid", INVALID_ACCOUNTS)
async def test_invalid_account_refuses_and_cleans_up(audit, session, invalid, capsys):
    module, sdk, gateway, _ = audit
    accounts = [SimpleNamespace(login=101, trade_mode=0), SimpleNamespace(login=202, trade_mode=0)]
    accounts[session] = invalid
    sdk.account_info.side_effect = accounts
    with pytest.raises(RuntimeError) as exc:
        await module.main()
    assert "909090" not in str(exc.value)
    assert "refused" in str(exc.value) or "required" in str(exc.value)
    gateway.disconnect.assert_awaited_once()
    assert gateway.get_account_info.await_count == session
    assert sdk.initialize.call_count == session
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("session", [0, 1], ids=["first", "second"])
@pytest.mark.parametrize("mode", ["live", "contest", "unknown", None, 0, False, "DEMO"])
async def test_conflicting_or_unknown_gateway_environment_refuses(audit, session, mode, capsys):
    module, sdk, gateway, _ = audit
    reads = [SimpleNamespace(account_id="101", trade_mode="demo"), SimpleNamespace(account_id="202", trade_mode="demo")]
    reads[session].trade_mode = mode
    gateway.get_account_info.side_effect = reads
    with pytest.raises(RuntimeError, match="not explicitly DEMO"):
        await module.main()
    gateway.disconnect.assert_awaited_once()
    assert sdk.initialize.call_count == session
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("session", [0, 1], ids=["first", "second"])
async def test_conflicting_identity_refuses_without_disclosure(audit, session, capsys):
    module, _, gateway, _ = audit
    reads = [SimpleNamespace(account_id="101", trade_mode="demo"), SimpleNamespace(account_id="202", trade_mode="demo")]
    reads[session].account_id = "909090"
    gateway.get_account_info.side_effect = reads
    with pytest.raises(RuntimeError, match="observations conflict") as exc:
        await module.main()
    assert "909090" not in str(exc.value)
    assert capsys.readouterr().out == ""
    gateway.disconnect.assert_awaited_once()


@pytest.mark.parametrize("session", [0, 1], ids=["first", "second"])
async def test_missing_gateway_environment_refuses(audit, session, capsys):
    module, _, gateway, _ = audit
    reads = [SimpleNamespace(account_id="101", trade_mode="demo"), SimpleNamespace(account_id="202", trade_mode="demo")]
    del reads[session].trade_mode
    gateway.get_account_info.side_effect = reads
    with pytest.raises(RuntimeError, match="not explicitly DEMO"):
        await module.main()
    gateway.disconnect.assert_awaited_once()
    assert capsys.readouterr().out == ""


async def test_confirmed_demo_accounts_succeed_and_redact(audit, capsys):
    module, _, gateway, _ = audit
    assert await module.main() == 0
    captured = capsys.readouterr().out
    output = json.loads(captured)
    assert output["first_demo_verified"] is True
    assert output["second_demo_verified"] is True
    assert output["account_identity_changed"] is True
    assert output["first_handle_initial_matches_first_session"] is True
    assert output["first_handle_after_switch_matches_second_session"] is True
    assert "101" not in captured and "202" not in captured
    gateway.disconnect.assert_awaited_once()


async def test_no_opt_in_refuses_before_gateway_construction(audit, monkeypatch):
    module, sdk, gateway, constructor = audit
    monkeypatch.delenv("JQE_RUN_MT5_PROCESS_GLOBAL_AUDIT")
    with pytest.raises(RuntimeError, match="JQE_RUN_MT5_PROCESS_GLOBAL_AUDIT"):
        await module.main()
    constructor.assert_not_called()
    sdk.initialize.assert_not_called()
    gateway.connect.assert_not_awaited()


async def test_second_initialization_failure_cleans_up(audit, capsys):
    module, sdk, gateway, _ = audit
    sdk.initialize.return_value = False
    with pytest.raises(RuntimeError, match="Second terminal initialization failed"):
        await module.main()
    gateway.disconnect.assert_awaited_once()
    assert capsys.readouterr().out == ""
