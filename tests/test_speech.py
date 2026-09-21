"""The station's voice: that it says the right things, and only from measurements.

The load-bearing claim here is that the spoken surface is finite and therefore
completely pre-rendered. That is only true if three things stay in step: the
phrase list, the crew names, and the files on disk. Nothing catches a drift
between them except these tests, and the way a drift shows up on stage is
silence — the one failure nobody notices in rehearsal because it looks like
the sound being off.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server.speech import (  # noqa: E402
    MAX_WORDS,
    PHRASES,
    Announcer,
    Utterance,
    every_clip,
    name_stem,
)

SPEECH_DIR = ROOT / "web" / "speech"
VOICE_JS = (ROOT / "web" / "voice.js").read_text(encoding="utf-8")


def _row(pid: str, name: str, urgency: str, total: int = 0, single: bool = False) -> dict:
    return {
        "patient": {"id": pid, "name": name},
        "triage": {"urgency": urgency, "total": total, "single_param_3": single},
    }


# ------------------------------------------------ it speaks on changes only

def test_nothing_is_said_on_the_first_sight_of_a_crew_member():
    """Otherwise starting the program announces forty people at once."""
    a = Announcer()
    assert a.on_board([_row("P-01", "Clara Dubois", "high", 7)]) == []


def test_crossing_into_high_is_announced_once_not_every_frame():
    """The board updates ten times a second. A station that announced a HIGH
    band ten times a second is a station whose sound gets turned off."""
    a = Announcer()
    a.on_board([_row("P-01", "Clara Dubois", "routine")])
    said = a.on_board([_row("P-01", "Clara Dubois", "high", 7)])
    assert [u.phrase for u in said] == ["band_high"]
    assert a.on_board([_row("P-01", "Clara Dubois", "high", 7)]) == []


def test_the_single_parameter_rule_gets_its_own_line():
    """"NEWS2 three" sounds reassuring out loud. When the band came from one
    parameter scoring 3 on its own, saying the aggregate would mislead."""
    a = Announcer()
    a.on_board([_row("P-02", "Ines Novak", "routine")])
    said = a.on_board([_row("P-02", "Ines Novak", "medium", 3, single=True)])
    assert [u.phrase for u in said] == ["band_single_param"]


def test_drifting_back_down_is_not_narrated():
    """Only escalations and a return to normal. Low to medium and back is the
    machine thinking out loud."""
    a = Announcer()
    a.on_board([_row("P-03", "Yara Kaur", "medium")])
    assert a.on_board([_row("P-03", "Yara Kaur", "low")]) == []


def test_flapping_across_a_boundary_is_announced_once():
    """Found live: vitals are noisy, so somebody sitting on the medium
    boundary crosses it repeatedly, and tracking only the previous band
    announced the same four names over and over. That is how an operator
    learns to ignore the thing meant to interrupt them."""
    a = Announcer()
    a.on_board([_row("P-05", "Andrei Ferreira", "low")])
    first = a.on_board([_row("P-05", "Andrei Ferreira", "medium", 5)])
    a.on_board([_row("P-05", "Andrei Ferreira", "low")])
    second = a.on_board([_row("P-05", "Andrei Ferreira", "medium", 5)])
    assert [u.phrase for u in first] == ["band_medium"]
    assert second == [], "the same news, told twice"


def test_getting_genuinely_worse_is_still_announced():
    """The high-water mark must not silence a real escalation."""
    a = Announcer()
    a.on_board([_row("P-05", "Andrei Ferreira", "low")])
    a.on_board([_row("P-05", "Andrei Ferreira", "medium", 5)])
    said = a.on_board([_row("P-05", "Andrei Ferreira", "high", 8)])
    assert [u.phrase for u in said] == ["band_high"]


def test_recovering_re_arms_the_alerts():
    """Somebody who got better and then relapses must be announced again."""
    a = Announcer()
    a.on_board([_row("P-06", "Clara Dubois", "low")])
    a.on_board([_row("P-06", "Clara Dubois", "high", 8)])
    a.on_board([_row("P-06", "Clara Dubois", "routine")])
    said = a.on_board([_row("P-06", "Clara Dubois", "high", 8)])
    assert [u.phrase for u in said] == ["band_high"]


def test_recovery_is_worth_saying():
    a = Announcer()
    a.on_board([_row("P-03", "Yara Kaur", "high", 7)])
    said = a.on_board([_row("P-03", "Yara Kaur", "routine")])
    assert [u.phrase for u in said] == ["band_clear"]


# ------------------------------------------------------------ the assistant

def test_the_station_announces_its_own_assistant_dying():
    """The beat the whole demo is built on, and it is literally true: this line
    is spoken by the fast track while every number on screen keeps updating."""
    a = Announcer()
    a.on_ai(True, False)
    assert [u.phrase for u in a.on_ai(False, False)] == ["ai_down"]


def test_booting_is_not_an_event():
    """Announcing "the assistant has stopped" because it had not finished
    probing yet would be a lie told at start-up."""
    a = Announcer()
    assert a.on_ai(False, False) == []


def test_a_stand_in_says_so_out_loud_too():
    a = Announcer()
    assert [u.phrase for u in a.on_ai(True, True)] == ["ai_stand_in"]


def test_a_reset_does_not_re_announce_the_assistant():
    """Its state belongs to the machine, not to the scenario."""
    a = Announcer()
    a.on_ai(True, False)
    a.reset()
    assert a.on_ai(True, False) == []


def test_a_zone_seals_once_not_for_as_long_as_it_stays_sealed():
    a = Announcer()
    first = a.on_quarantine({}, ["A"])
    again = a.on_quarantine({}, ["A"])
    assert [u.phrase for u in first] == ["zone_a_sealed"]
    assert again == []


def test_each_zone_is_named_so_two_closing_does_not_sound_like_a_stuck_machine():
    """Both zones sealing during the outbreak said the identical sentence
    twice, which reads as the machine repeating itself rather than as the
    contamination spreading."""
    a = Announcer()
    a.on_quarantine({}, ["A"])
    said = a.on_quarantine({}, ["A", "B"])
    assert [u.phrase for u in said] == ["zone_b_sealed"]


# -------------------------------------------- it can only say what exists

def test_every_line_it_can_reach_has_a_file():
    """A phrase with no rendered clip is silence on stage, which in rehearsal
    is indistinguishable from the sound being switched off."""
    from tools.render_speech import crew_names

    have = {p.stem for p in SPEECH_DIR.glob("*.wav")}
    need = set(every_clip(crew_names()))
    assert not (need - have), f"no clip rendered for: {sorted(need - have)}"


def test_no_clip_exists_that_nothing_can_ever_play():
    from tools.render_speech import crew_names

    have = {p.stem for p in SPEECH_DIR.glob("*.wav")}
    need = set(every_clip(crew_names()))
    assert not (have - need), f"orphaned clips: {sorted(have - need)}"


def test_the_browser_builds_the_same_filename_as_python():
    """Two implementations of one rule. A mismatch is a silent 404 per crew
    member, and silence is exactly what this feature's failure looks like."""
    js = re.search(r'function nameStem\(name\) \{(.+?)\n  \}', VOICE_JS, re.S)
    assert js, "nameStem() not found in web/voice.js"
    for name in ["Clara Dubois", "Jean-Luc O'Brien", "Yara  Kaur", "Ines Novak"]:
        expected = "name_" + re.sub(r"^_+|_+$", "", re.sub(r"[^a-z0-9]", "_", name.lower()))
        assert name_stem(name) == expected, f"python disagrees on {name!r}"


# ------------------------------------------------------------ what it says

def test_no_spoken_line_is_longer_than_the_operator_can_hold():
    """An alert the operator cannot keep in their head while looking at a
    patient has stopped being an alert and become narration."""
    for key, text in PHRASES.items():
        assert len(text.split()) <= MAX_WORDS, f"{key} is {len(text.split())} words: {text!r}"


def test_nothing_spoken_names_a_condition_or_a_treatment():
    """The station speaks from measurements. The assistant's words are never
    spoken, because a sentence said out loud carries far more authority than
    the same sentence on screen, and the one output we cannot constrain is the
    one that must never get a voice."""
    banned = ("pneumonia", "sepsis", "infection", "diagnos", "paracetamol",
              "oxygen", "administer", "dose", "mg", "treat")
    for key, text in PHRASES.items():
        low = text.lower()
        for word in banned:
            assert word not in low, f"{key} says {word!r}: {text!r}"


def test_an_utterance_renders_the_full_sentence_for_captions():
    u = Utterance("band_high", "P-01", "Clara Dubois")
    assert u.to_dict()["text"] == "Clara Dubois. NEWS2 seven or above. Emergency response."
