"""Repository-level guards for application order-submission boundaries."""

from __future__ import annotations

import ast
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
APPLICATION_ROOTS = (
    "analytics",
    "api",
    "backtesting",
    "broker",
    "config",
    "core",
    "data",
    "execution",
    "intelligence",
    "risk",
    "strategy",
    "tools",
)
ALLOWED_DIRECT_SUBMIT_MODULES = frozenset(
    {
        "execution/executor.py",  # Canonical durable application submission boundary.
    }
)


def _direct_submit_order_calls(path: Path) -> tuple[int, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return tuple(
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "submit_order"
    )


def _application_python_files() -> tuple[Path, ...]:
    files = [REPOSITORY_ROOT / "main.py"]
    for directory in APPLICATION_ROOTS:
        files.extend((REPOSITORY_ROOT / directory).rglob("*.py"))
    return tuple(files)


def test_only_explicit_application_boundaries_call_submit_order() -> None:
    observed = {
        path.relative_to(REPOSITORY_ROOT).as_posix(): _direct_submit_order_calls(path)
        for path in _application_python_files()
        if _direct_submit_order_calls(path)
    }

    assert set(observed) == ALLOWED_DIRECT_SUBMIT_MODULES, observed
    assert all(len(lines) == 1 for lines in observed.values()), observed


def test_guard_detects_an_unauthorized_direct_submit_order_call(tmp_path: Path) -> None:
    unauthorized = tmp_path / "rogue.py"
    unauthorized.write_text(
        "async def bypass(gateway, order):\n"
        "    return await gateway.submit_order(order)\n",
        encoding="utf-8",
    )

    assert _direct_submit_order_calls(unauthorized) == (2,)


def test_guard_accepts_current_explicit_boundaries() -> None:
    for relative_path in ALLOWED_DIRECT_SUBMIT_MODULES:
        assert _direct_submit_order_calls(REPOSITORY_ROOT / relative_path)


def test_main_has_no_direct_submission_bypass() -> None:
    assert _direct_submit_order_calls(REPOSITORY_ROOT / "main.py") == ()


def test_legacy_order_manager_submission_boundary_is_removed() -> None:
    assert not (REPOSITORY_ROOT / "execution" / "order_manager.py").exists()
