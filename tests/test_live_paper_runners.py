"""Safety-boundary tests for the executable live-paper launchers."""

from __future__ import annotations

import argparse
import ast
import inspect
from pathlib import Path

import pytest

from tools import run_deriv_live_paper, run_mt5_live_paper


def _args(tmp_path: Path, *, deriv: bool) -> argparse.Namespace:
    values: dict[str, object] = {
        "symbol": "R_75",
        "timeframe": "M15",
        "max_candles": 1,
        "max_duration_seconds": 30.0,
        "poll_seconds": 1.0,
        "output": tmp_path / "output.json",
        "evidence": tmp_path / "evidence.sqlite3",
        "ledger": tmp_path / "ledger.sqlite3",
    }
    if deriv:
        values["max_orders"] = 1
    return argparse.Namespace(**values)


@pytest.mark.parametrize(
    "execution_enabled", ["false", None], ids=["disabled", "absent"],
)
@pytest.mark.parametrize(
    ("runner", "deriv"),
    [
        pytest.param(run_mt5_live_paper, False, id="mt5"),
        pytest.param(run_deriv_live_paper, True, id="deriv"),
    ],
)
def test_runner_refuses_external_execution_disabled(
    runner, deriv: bool, execution_enabled: str | None,
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A launcher must exit before constructing a gateway when config is disabled."""
    # Isolate the absent case from the repository's local .env configuration.
    monkeypatch.chdir(tmp_path)
    if execution_enabled is None:
        monkeypatch.delenv("JQE_BROKER_EXECUTION_ENABLED", raising=False)
    else:
        monkeypatch.setenv("JQE_BROKER_EXECUTION_ENABLED", execution_enabled)
    monkeypatch.setattr(runner, "_arguments", lambda: _args(tmp_path, deriv=deriv))

    gateway_constructed = False

    def forbidden_gateway(_settings):
        nonlocal gateway_constructed
        gateway_constructed = True
        raise AssertionError("gateway construction must not be reached")

    monkeypatch.setattr(runner, "get_gateway", forbidden_gateway)

    with pytest.raises(SystemExit) as exc_info:
        runner.main()

    assert exc_info.value.code != 0
    assert "JQE_BROKER_EXECUTION_ENABLED" in str(exc_info.value)
    assert "disabled" in str(exc_info.value).lower()
    assert gateway_constructed is False


@pytest.mark.parametrize("runner", [run_mt5_live_paper, run_deriv_live_paper])
def test_runner_never_overrides_execution_enablement(runner) -> None:
    """Only externally loaded Settings may supply the execution authorization."""
    tree = ast.parse(inspect.getsource(runner))
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    references = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            # Also reject setattr/model-copy/dictionary injection of this field.
            assert node.value != "broker_execution_enabled"
            if "JQE_BROKER_EXECUTION_ENABLED" in node.value:
                # The name may occur in the refusal message, never as an env key.
                parent = parents[node]
                assert isinstance(parent, ast.Call)
                assert isinstance(parent.func, ast.Name)
                assert parent.func.id == "ConfigurationError"
                assert "disabled" in node.value.lower()
        if isinstance(node, ast.Attribute) and node.attr == "broker_execution_enabled":
            assert isinstance(node.ctx, ast.Load)
            assert isinstance(node.value, ast.Name) and node.value.id == "configured"
            references.append(node)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id == "Settings":
                assert not node.args
                assert all(keyword.arg is not None for keyword in node.keywords)
                for keyword in node.keywords:
                    if keyword.arg == "broker_execution_enabled":
                        assert isinstance(keyword.value, ast.Attribute)
                        assert keyword.value.attr == "broker_execution_enabled"
                        assert isinstance(keyword.value.value, ast.Name)
                        assert keyword.value.value.id == "configured"
    assert references
    # The external settings object itself must be loaded without overrides.
    configured_assignments = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "configured" for target in node.targets)
    ]
    assert len(configured_assignments) == 1
    value = configured_assignments[0].value
    assert isinstance(value, ast.Call) and isinstance(value.func, ast.Name)
    assert value.func.id == "Settings" and not value.args and not value.keywords
