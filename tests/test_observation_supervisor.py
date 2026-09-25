import ast
from datetime import datetime, timezone

from monitoring.observation_supervisor import ObservationSupervisor


def test_next_m5_close_is_utc_boundary():
    got = ObservationSupervisor.next_m5_close(datetime(2026, 9, 24, 4, 17, 49, tzinfo=timezone.utc))
    assert got == datetime(2026, 9, 24, 4, 20, tzinfo=timezone.utc)


def test_supervisor_has_no_execution_import_or_order_submission():
    tree = ast.parse(open("monitoring/observation_supervisor.py", encoding="utf-8").read())
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            assert not any(alias.name == "execution" or alias.name.startswith("execution.") for alias in node.names)
        if isinstance(node, ast.Attribute):
            assert node.attr not in {"submit_order", "order_send"}

