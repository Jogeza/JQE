import ast
import json

import pytest

from config.settings import Settings
from monitoring import painx1200_forward_collector
from research.painx1200_forward_candidate import candidate_record, family_conclusion, write_locked_records


def test_candidate_and_failed_family_records_are_separate_and_immutable(tmp_path):
    family_path, candidate_path = write_locked_records(tmp_path)
    assert json.loads(family_path.read_text(encoding="utf-8")) == family_conclusion()
    assert json.loads(candidate_path.read_text(encoding="utf-8")) == candidate_record()
    assert family_conclusion()["historical_definition_unchanged"] is True
    assert candidate_record()["success_criteria"]["minimum_resolved_non_overlapping_buy_entries"] == 500
    candidate_path.write_text("{}", encoding="utf-8")
    with pytest.raises(RuntimeError, match="locked record differs"):
        write_locked_records(tmp_path)


def test_forward_collector_module_has_no_submission_route():
    tree = ast.parse(open(painx1200_forward_collector.__file__, encoding="utf-8").read())
    imported = []
    attributes = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
        elif isinstance(node, ast.Attribute):
            attributes.append(node.attr)
    assert not any(name == "execution" or name.startswith("execution.") for name in imported)
    assert "broker.factory" not in imported
    assert "broker.mt5_gateway" not in imported
    assert "submit_order" not in attributes
    assert "order_send" not in attributes


def test_forward_collector_refuses_execution_enabled_settings(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    write_locked_records("state")
    with pytest.raises(RuntimeError, match="execution is enabled"):
        painx1200_forward_collector.PainX1200ForwardCollector(
            Settings(broker_execution_enabled=True, _env_file=None), root=tmp_path / "runtime"
        )
