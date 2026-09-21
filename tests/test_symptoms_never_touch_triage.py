"""The separation between what is said and what is measured.

These are the most important tests in the project. Everything else here is a
feature; this is the claim MedBox makes about itself. If a reported symptom
could move a NEWS2 score, then the score would no longer mean what the Royal
College of Physicians says it means, and a crew member could talk themselves
into an emergency response.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server import triage  # noqa: E402
from server.symptoms import PER_PATIENT, SymptomLog  # noqa: E402

WELL = dict(temperature=36.8, spo2=98.0, pulse=72.0, respiration=16.0)


def test_reporting_a_symptom_cannot_change_the_score():
    """The whole safety argument, as an assertion."""
    before = triage.assess(**WELL)

    log = SymptomLog()
    for said in (
        "I have had a headache since this morning",
        "I keep coughing",
        "I feel like I am dying",
        "I cannot breathe at all",          # alarming, and still not a measurement
    ):
        log.add("P-01", said)

    after = triage.assess(**WELL)
    assert after.total == before.total == 0
    assert after.urgency == before.urgency
    assert log.for_patient("P-01"), "the symptoms were recorded"


def test_triage_does_not_know_this_module_exists():
    """Static guard on the architecture rule, not just on today's behaviour.

    A future edit that wires reported symptoms into scoring would pass the
    test above if it were subtle enough. This one fails the moment the
    measurement path so much as mentions them.
    """
    source = (ROOT / "server" / "triage.py").read_text(encoding="utf-8").lower()
    for forbidden in ("symptom", "reported", "import ai", "from .ai"):
        assert forbidden not in source, (
            f"server/triage.py refers to {forbidden!r}; the measurement path "
            "must not depend on anything a crew member says or on the AI"
        )


def test_every_record_is_flagged_as_not_measured():
    log = SymptomLog()
    entry = log.add("P-01", "my chest hurts")
    assert entry.to_dict()["measured"] is False
    assert all(r["measured"] is False for r in log.for_patient("P-01"))


def test_the_prompt_tells_a_small_model_these_are_unverified():
    """A 3B model will not infer it from a heading, so it must be spelled out."""
    log = SymptomLog()
    log.add("P-01", "I have had a headache since this morning")
    note = log.prompt_note("P-01")
    assert "NEWS2" in note
    assert "NOT part" in note
    assert "headache" in note


def test_no_symptoms_means_no_prompt_block_at_all():
    assert SymptomLog().prompt_note("P-01") == ""


def test_voice_keeps_its_confidence_and_typing_has_none():
    log = SymptomLog()
    heard = log.add("P-01", "I keep coughing", source="voice", confidence=0.82)
    typed = log.add("P-01", "my chest hurts", source="typed")
    assert heard.confidence == 0.82
    assert typed.confidence is None


def test_empty_and_unknown_sources_are_refused():
    log = SymptomLog()
    with pytest.raises(ValueError):
        log.add("P-01", "   ")
    with pytest.raises(ValueError):
        log.add("P-01", "something", source="telepathy")


def test_only_the_recent_ones_are_kept_and_newest_reads_first():
    log = SymptomLog()
    for i in range(PER_PATIENT + 4):
        log.add("P-01", f"statement {i}")
    got = log.for_patient("P-01")
    assert len(got) == PER_PATIENT
    assert got[0]["text"] == f"statement {PER_PATIENT + 3}"


def test_crew_members_do_not_share_statements():
    log = SymptomLog()
    log.add("P-01", "my head hurts")
    assert log.for_patient("P-02") == []


def test_recording_reaches_storage_with_its_source():
    seen = []
    log = SymptomLog(on_record=lambda kind, detail, pid: seen.append((kind, detail, pid)))
    log.add("P-01", "I keep coughing", source="voice", confidence=0.82)
    assert seen and seen[0][0] == "symptom"
    assert "voice" in seen[0][1] and "82%" in seen[0][1]
    assert seen[0][2] == "P-01"
