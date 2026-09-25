from research.current_research_status import current_research_status, write_current_research_status
from research.painx1200_forward_candidate import candidate_record


def test_current_status_does_not_rewrite_locked_candidate(tmp_path):
    locked_before = candidate_record()
    status = current_research_status()
    assert status["status"] == "NO_DEMONSTRATED_POSITIVE_EDGE"
    assert status["painx1200_m1_buy"]["demonstrated_positive_edge"] is False
    assert status["painx1200_m1_buy"]["corrected_historical_gap_aware_average_r"] < 0
    assert status["painx1200_m1_buy"]["locked_definition_and_success_criteria_changed"] is False
    write_current_research_status(tmp_path / "status.json")
    assert candidate_record() == locked_before
