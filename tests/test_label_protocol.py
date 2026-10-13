from datetime import datetime, timedelta, timezone

from backtesting.label_protocol import eligibility


def times(count=30):
    return tuple(datetime(2026, 9, 8, tzinfo=timezone.utc) + timedelta(minutes=5*i) for i in range(count))


def test_full_horizon_includes_nineteenth_entry_bar():
    bars = times()
    assert eligibility(bars, 10, bars[-1]+timedelta(minutes=5)).startswith("ELIGIBLE")
    assert eligibility(bars, 11, bars[-1]+timedelta(minutes=5)) == "CENSORED_INCOMPLETE_HORIZON"


def test_boundary_never_becomes_end_of_data_return():
    bars = times()
    assert eligibility(bars, 5, bars[24]) == "CENSORED_PARTITION_BOUNDARY"
    assert eligibility(bars, 5, bars[25]).startswith("ELIGIBLE")


def test_gap_anywhere_in_full_horizon_censors_even_potential_early_exit():
    bars = times(40)
    bars = bars[:20] + tuple(t+timedelta(minutes=5) for t in bars[20:])
    assert eligibility(bars, 5, bars[-1]) == "CENSORED_GAP"


def test_recent_feature_history_gap_censors():
    bars = times(40)
    bars = bars[:4] + tuple(t+timedelta(minutes=5) for t in bars[4:])
    assert eligibility(bars, 5, bars[-1]) == "CENSORED_GAP"


def test_old_gap_outside_local_window_not_a_pretext_to_remove_event():
    bars = times(40)
    bars = bars[:1] + tuple(t+timedelta(minutes=5) for t in bars[1:])
    assert eligibility(bars, 5, bars[-1]).startswith("ELIGIBLE")
