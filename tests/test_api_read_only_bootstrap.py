"""The API process cannot inherit broker execution authority."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


def test_api_bootstrap_forces_execution_disabled_even_if_shared_env_arms_it(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(
        "JQE_BROKER=weltrade\nJQE_MARKET_DATA_SOURCE=broker\n"
        "JQE_BROKER_EXECUTION_ENABLED=true\n",
        encoding="utf-8",
    )
    root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(root)
    environment["JQE_BROKER_EXECUTION_ENABLED"] = "true"
    result = subprocess.run(
        [sys.executable, "-c", "import api.app; from config.settings import settings; "
         "print('API_EXECUTION_ENABLED=' + str(settings.broker_execution_enabled))"],
        cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "API_EXECUTION_ENABLED=False" in result.stdout


def test_api_refuses_a_preloaded_execution_enabled_settings_object(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(root)
    environment["JQE_BROKER_EXECUTION_ENABLED"] = "true"
    result = subprocess.run(
        [sys.executable, "-c", "import config.settings; import api.app"],
        cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=20,
        check=False,
    )
    assert result.returncode != 0
    assert "API refuses execution-enabled settings" in result.stderr
