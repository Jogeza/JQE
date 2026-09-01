"""Offline tests proving the MT5 live-diagnostic gate is fail-closed.

These tests verify that ``test_mt5_connection_live.py`` cannot contact a real
MT5 terminal during an ordinary (default) pytest run.

All assertions are made without importing MetaTrader5 or making any broker
contact.  The gate logic is validated by inspecting the skip marker that is
applied to the live test function.
"""

from __future__ import annotations

import importlib
import sys
import types
from unittest.mock import MagicMock

_LIVE_MODULE = "tests.test_mt5_connection_live"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reload_live_module(env: dict[str, str], monkeypatch) -> types.ModuleType:
    """Re-import the live MT5 test module with a custom env snapshot.

    Uses monkeypatch so the real environment is restored after each test.
    The module is removed from sys.modules before reload to force
    re-evaluation of the module-level gate expression.
    """
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    # Ensure absent keys are truly absent.
    for key in ("JQE_RUN_LIVE_MT5_TESTS",):
        if key not in env:
            monkeypatch.delenv(key, raising=False)

    sys.modules.pop(_LIVE_MODULE, None)

    # Provide a harmless MetaTrader5 stub so the module can be imported on
    # machines where the real SDK is absent.
    if "MetaTrader5" not in sys.modules:
        stub = MagicMock(name="MetaTrader5Stub")
        sys.modules["MetaTrader5"] = stub

    return importlib.import_module(_LIVE_MODULE)


def _get_skip_marker(module: types.ModuleType):
    """Return the skipif marker applied to the live test function, or None."""
    fn = getattr(module, "test_mt5_connection", None)
    assert fn is not None, "test_mt5_connection function not found in live module"
    marks = getattr(fn, "pytestmark", [])
    for m in marks:
        if m.name == "skipif":
            return m
    return None


# ---------------------------------------------------------------------------
# Gate tests — no MT5 contact in any of these
# ---------------------------------------------------------------------------


def test_live_gate_is_skipped_when_env_var_absent(monkeypatch) -> None:
    """Default: env var absent → gate evaluates to SKIP."""
    mod = _reload_live_module(env={}, monkeypatch=monkeypatch)
    assert mod._LIVE_MT5_ENABLED is False, (
        "_LIVE_MT5_ENABLED must be False when JQE_RUN_LIVE_MT5_TESTS is absent"
    )
    marker = _get_skip_marker(mod)
    assert marker is not None, "skipif marker must be present on test_mt5_connection"
    # The condition stored in the marker must be True (i.e. skip is active).
    assert marker.args[0] is True, (
        "skipif condition must be True (→ skip) when env var is absent"
    )


def test_live_gate_is_skipped_for_empty_string(monkeypatch) -> None:
    """Explicit empty string → gate stays SKIP."""
    mod = _reload_live_module(env={"JQE_RUN_LIVE_MT5_TESTS": ""}, monkeypatch=monkeypatch)
    assert mod._LIVE_MT5_ENABLED is False


def test_live_gate_is_skipped_for_zero(monkeypatch) -> None:
    """'0' must NOT enable the gate."""
    mod = _reload_live_module(env={"JQE_RUN_LIVE_MT5_TESTS": "0"}, monkeypatch=monkeypatch)
    assert mod._LIVE_MT5_ENABLED is False


def test_live_gate_is_skipped_for_false_string(monkeypatch) -> None:
    """'false' must NOT enable the gate."""
    mod = _reload_live_module(env={"JQE_RUN_LIVE_MT5_TESTS": "false"}, monkeypatch=monkeypatch)
    assert mod._LIVE_MT5_ENABLED is False


def test_live_gate_is_skipped_for_yes_string(monkeypatch) -> None:
    """'yes' must NOT enable the gate (only the exact string '1' counts)."""
    mod = _reload_live_module(env={"JQE_RUN_LIVE_MT5_TESTS": "yes"}, monkeypatch=monkeypatch)
    assert mod._LIVE_MT5_ENABLED is False


def test_live_gate_is_skipped_for_true_string(monkeypatch) -> None:
    """'true' must NOT enable the gate."""
    mod = _reload_live_module(env={"JQE_RUN_LIVE_MT5_TESTS": "true"}, monkeypatch=monkeypatch)
    assert mod._LIVE_MT5_ENABLED is False


def test_live_gate_enabled_only_by_exact_one(monkeypatch) -> None:
    """Only the exact string '1' enables the gate.

    We verify the module-level flag flips to True when the opt-in is set.
    We do NOT call test_mt5_connection — that would attempt broker contact.
    """
    mod = _reload_live_module(env={"JQE_RUN_LIVE_MT5_TESTS": "1"}, monkeypatch=monkeypatch)
    assert mod._LIVE_MT5_ENABLED is True, (
        "_LIVE_MT5_ENABLED must be True when JQE_RUN_LIVE_MT5_TESTS=1"
    )
    # When enabled the skipif condition is False (do NOT skip).
    marker = _get_skip_marker(mod)
    assert marker is not None
    assert marker.args[0] is False, (
        "skipif condition must be False (→ run) when JQE_RUN_LIVE_MT5_TESTS=1"
    )


def test_collection_does_not_initialize_mt5(monkeypatch) -> None:
    """Importing the live-test module must not call mt5.initialize().

    This proves collection-safety: even when MetaTrader5 is importable,
    loading the test module must not trigger broker contact.
    """
    mt5_stub = MagicMock(name="MT5CollectionSafetyStub")
    monkeypatch.setitem(sys.modules, "MetaTrader5", mt5_stub)
    monkeypatch.delenv("JQE_RUN_LIVE_MT5_TESTS", raising=False)
    sys.modules.pop(_LIVE_MODULE, None)

    importlib.import_module(_LIVE_MODULE)

    mt5_stub.initialize.assert_not_called()
    mt5_stub.login.assert_not_called()
    mt5_stub.account_info.assert_not_called()
