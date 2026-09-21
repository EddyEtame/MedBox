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
