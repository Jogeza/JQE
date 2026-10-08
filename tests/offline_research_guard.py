"""Opt-in offline validation isolation: python -m pytest -p tests.offline_research_guard.

No assertions are skipped or weakened. Operator stores and terminal sessions
are inaccessible through default configuration during this test process.
"""
from contextlib import ExitStack
from pathlib import Path
import os
import tempfile
from unittest.mock import patch

_stack = ExitStack()


def pytest_configure(config):
    os.environ["JQE_RUN_LIVE_MT5_TESTS"] = "0"
    os.environ["JQE_RUN_LIVE_WELTRADE_TESTS"] = "0"
    from config.settings import Settings, settings
    Settings.model_config["env_file"] = None
    isolated = Path(tempfile.mkdtemp(prefix="jqe-entry-quality-tests-"))
    for name, field in Settings.model_fields.items():
        if (name.endswith("_path") or name in {"log_dir", "cache_dir"}) and not any(
            part in name for part in ("terminal", "portable")
        ):
            value = isolated / name
            setattr(settings, name, value)
        if any(part in name for part in ("password", "token", "login", "server", "terminal_path")) and field.default is None:
            setattr(settings, name, None)
    settings.broker_execution_enabled = False
    settings.telegram_enabled = False
    import MetaTrader5 as mt5
    for name in ("initialize", "login", "shutdown", "order_send"):
        _stack.enter_context(patch.object(mt5, name, side_effect=RuntimeError(
            "Real MT5 calls blocked: inject an offline SDK/gateway in this test"
        )))


def pytest_unconfigure(config):
    _stack.close()
