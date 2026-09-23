"""Tests for the NEWS2 engine.

These matter more than they look. The triage score is what the jury is shown
and what the quarantine logic keys off, so a silent regression here changes the
demo's behaviour without anything visibly breaking.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.triage import Urgency, assess, band  # noqa: E402


def test_healthy_crew_member_scores_zero():
    r = assess(temperature=36.8, spo2=98, pulse=72, respiration=15)
    assert r.total == 0
    assert r.urgency is Urgency.ROUTINE


def test_fever_alone_is_low_not_ignored():
    r = assess(temperature=38.5, spo2=98, pulse=80, respiration=16)
    assert r.total == 1
    assert r.urgency is Urgency.LOW


def test_respiratory_contamination_pattern_is_high():
    r = assess(temperature=39.2, spo2=91, pulse=125, respiration=26)
    # temp 2 + spo2 3 + pulse 2 + resp 3 = 10
    assert r.total == 10
    assert r.urgency is Urgency.HIGH


def test_single_parameter_three_escalates_on_its_own():
    """The NEWS2 rule people forget: one parameter at 3 escalates alone."""
    r = assess(temperature=36.8, spo2=91, pulse=72, respiration=15)
    assert r.total == 3
    assert r.has_single_param_3
    assert r.urgency is Urgency.MEDIUM


def test_missing_readings_are_not_scored_as_normal():
    r = assess(temperature=38.5)
    assert "spo2" not in r.measured_params
    assert "temperature" in r.measured_params
    # Absent parameters must contribute nothing rather than a reassuring zero.
    assert r.total == 1


def test_band_boundaries():
    assert band(0, False) is Urgency.ROUTINE
    assert band(4, False) is Urgency.LOW
    assert band(5, False) is Urgency.MEDIUM
    assert band(6, False) is Urgency.MEDIUM
    assert band(7, False) is Urgency.HIGH
    assert band(2, True) is Urgency.MEDIUM


def test_worst_parameter_is_reported_for_the_screen():
    r = assess(temperature=36.9, spo2=90, pulse=75, respiration=14)
    assert r.worst_param.name == "spo2"
    assert "hypox" in r.worst_param.reason


def test_the_clinical_response_is_said_in_french():
    """The panel shows this sentence under the band, to a French jury."""
    from server.triage import Urgency

    for band in Urgency:
        assert band.response.endswith("."), band.response
        assert not any(word in band.response for word in ("review", "monitoring", "response")), band.response


def test_systolic_pressure_scores_as_the_rcp_2017_table():
    """3 at 90 or below, 2 at 91-100, 1 at 101-110, 0 at 111-219, 3 at 220+."""
    from server.triage import score_systolic_bp

    assert [score_systolic_bp(v).score for v in (80, 90, 91, 100, 101, 110, 111, 219, 220)] == \
        [3, 3, 2, 2, 1, 1, 0, 0, 3]
    assert score_systolic_bp(None).measured is False


def test_the_seven_parameters_make_a_complete_news2_only_when_all_are_there():
    """Five instruments plus two observations. Missing ones are assumed
    normal and the result says the screen is partial and names them."""
    from server.triage import assess

    partial = assess(temperature=36.8, spo2=98, pulse=72, respiration=15)
    assert partial.to_dict()["complete_news2"] is False
    assert partial.to_dict()["missing_news2"] == ["systolic_bp", "consciousness", "oxygen"]
    full = assess(temperature=36.8, spo2=98, pulse=72, respiration=15, systolic_bp=118,
                  consciousness="A", on_oxygen=False)
    assert full.to_dict()["complete_news2"] is True and full.total == 0
    assert full.to_dict()["score_label"].startswith("NEWS2 complet")


def test_acvpu_and_oxygen_observed_by_a_person_score_and_escalate():
    from server.triage import Urgency, assess

    confused = assess(temperature=36.8, spo2=98, pulse=72, respiration=15, systolic_bp=118,
                      consciousness="C", on_oxygen=False)
    assert confused.total == 3 and confused.urgency is Urgency.MEDIUM, "new confusion is a 3 on its own"
    on_o2 = assess(temperature=36.8, spo2=98, pulse=72, respiration=15, systolic_bp=118,
                   consciousness="A", on_oxygen=True)
    assert on_o2.total == 2 and on_o2.urgency is Urgency.LOW
    import pytest as _pytest
    with _pytest.raises(ValueError):
        assess(consciousness="Z")


def test_a_healthy_baseline_never_scores_on_pressure():
    """The healthy range must sit inside NEWS2's zero band (111-219), noise
    included: 106-128 put crew members at LOW while resting."""
    from server.sensors.synthetic import HEALTHY_BASELINE_RANGES
    from server.triage import score_systolic_bp

    low, high = HEALTHY_BASELINE_RANGES["systolic_bp"]
    assert score_systolic_bp(low - 3).score == 0 and score_systolic_bp(high + 3).score == 0
