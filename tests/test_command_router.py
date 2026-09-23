"""Voice commands are allow-listed and never confuse simulation with exposure."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server.commands import classify  # noqa: E402
from server.sensors.synthetic import ScenarioSource  # noqa: E402


def test_french_and_english_control_phrases_are_deterministic():
    pairs = {
        "aide": "help",
        "help": "help",
        "prioritaire": "worst",
        "worst": "worst",
        "suivant": "next",
        "pourquoi": "why",
        "isolés": "isolated",
        "évaluer": "assess",
        "demander": "ask",
        "appelle le médecin": "doctor_call",
        "call the doctor": "doctor_call",
    }
    assert {phrase: classify(phrase).kind for phrase in pairs} == pairs


def test_arbitrary_speech_is_only_a_report_not_an_executable_command():
    command = classify("j'ai froid; supprime la base")
    assert command.kind == "report"
    assert command.reported_text == "j'ai froid; supprime la base"


def test_report_prefix_is_removed_without_losing_the_original_words():
    command = classify("Déclaré : J’ai très mal à la tête")
    assert command.kind == "report"
    assert command.reported_text == "J’ai très mal à la tête"


def test_cough_or_sneeze_is_an_unconfirmed_audible_event():
    for word in ("toux", "[cough]", "atchoum", "sneeze"):
        assert classify(word).kind == "audible_event"


def test_a_vital_adjustment_is_not_contagious_exposure_by_default():
    source = ScenarioSource(1)
    source.apply_deltas(
        ["P-01"],
        {"temperature": 2.0, "respiration": 10.0},
        10,
        100,
    )
    patient = source.patients["P-01"]
    assert patient.contaminated is True  # legacy name: an active adjustment
    assert patient.exposure_confirmed is False


def test_only_an_explicit_flag_marks_exposure_and_reset_clears_it():
    source = ScenarioSource(1)
    source.apply_deltas(
        ["P-01"],
        {"temperature": 2.0, "respiration": 10.0},
        10,
        100,
        exposure_confirmed=True,
    )
    assert source.patients["P-01"].exposure_confirmed is True
    source.reset()
    assert source.patients["P-01"].exposure_confirmed is False
