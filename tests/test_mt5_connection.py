"""Pure lifecycle tests for the MT5 connection wrapper."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from core.mt5_connection import connect, disconnect


@patch("core.mt5_connection.mt5")
def test_explicit_terminal_path_is_passed_to_initialize(mock_mt5: MagicMock, tmp_path: Path) -> None:
    terminal = tmp_path / "terminal64.exe"
    terminal.touch()
    mock_mt5.initialize.return_value = True
    assert connect(terminal_path=terminal) is True
    mock_mt5.initialize.assert_called_once_with(str(terminal.resolve()))


@patch("core.mt5_connection.mt5")
def test_invalid_terminal_path_fails_without_initialize(mock_mt5: MagicMock, tmp_path: Path) -> None:
    assert connect(terminal_path=tmp_path / "missing.exe") is False
    mock_mt5.initialize.assert_not_called()


@patch("core.mt5_connection.mt5")
def test_initialize_failure_is_explicit(mock_mt5: MagicMock) -> None:
    mock_mt5.initialize.return_value = False
    assert connect() is False
    mock_mt5.login.assert_not_called()


@patch("core.mt5_connection.mt5")
def test_login_failure_shuts_down(mock_mt5: MagicMock) -> None:
    mock_mt5.initialize.return_value = True
    mock_mt5.login.return_value = False
    assert connect(login=42, password="secret", server="Demo") is False
    mock_mt5.shutdown.assert_called_once()


@patch("core.mt5_connection.mt5")
def test_shutdown_is_explicit(mock_mt5: MagicMock) -> None:
    disconnect()
    mock_mt5.shutdown.assert_called_once()
