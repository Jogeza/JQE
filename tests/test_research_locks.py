import json

import pytest

from research.forward_hypothesis import predeclared_record, write_predeclared_record
from research.holdout_registry import HoldoutConsumedError, assert_holdout_available_for_selection, write_consumed_record


def test_consumed_holdout_rejects_selection(tmp_path):
    path = tmp_path / "holdout.json"
    write_consumed_record(path)
    with pytest.raises(HoldoutConsumedError):
        assert_holdout_available_for_selection(path)


def test_forward_hypothesis_is_immutable_after_declaration(tmp_path):
    path = tmp_path / "hypothesis.json"
    write_predeclared_record(path)
    assert json.loads(path.read_text()) == predeclared_record()
    write_predeclared_record(path)
