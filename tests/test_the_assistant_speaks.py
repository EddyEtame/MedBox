"""The assistant's own words can be heard, and the voice never touches the board.

Piper renders French on the server, off the event loop; the browser asks for
one WAV per sentence and falls back to the pre-rendered clips when there is
no voice. The fast track does not know the voice exists.
"""
from __future__ import annotations

import asyncio
import io
import re
import sys
import wave
from pathlib import Path

import pytest
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server import tts  # noqa: E402


def test_the_fast_track_never_imports_the_voice():
    for rel in ("server/triage.py", "server/db.py", "server/quarantine.py",
                "server/sensors/base.py", "server/sensors/synthetic.py"):
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert not re.search(r"\btts\b", src), f"{rel} reaches for the voice"


def test_numbers_and_units_are_spoken_the_french_way():
    spoken = tts.normalise("Température 38.3 °C, SpO2 98.9 %, pouls 107 /min, tension 121 mmHg. MedBox, NEWS2 5.")
    assert "38,3" in spoken and "degrés" in spoken and "pour cent" in spoken
    assert "par minute" in spoken and "millimètres de mercure" in spoken
    assert "Med Box" in spoken and "score d’alerte" in spoken
    assert "SpO2" not in spoken and "°" not in spoken
    assert len(tts.normalise("x" * 2000)) == tts.MAX_CHARS


def test_a_missing_voice_is_reported_not_raised_further_up(tmp_path):
    speaker = tts.Speaker(tmp_path / "nowhere.onnx")
    assert speaker.available() is False
    with pytest.raises(RuntimeError):
        speaker.render("bonjour")
    assert "aucune voix" in (speaker.last_error or "")
    with pytest.raises(ValueError):
        speaker.render("   ")


def test_the_route_answers_503_without_a_voice_and_400_for_nonsense(monkeypatch, tmp_path):
    from server import app as station

    monkeypatch.setattr(station, "speaker_for", lambda lang: tts.Speaker(tmp_path / "nowhere.onnx"))
    with pytest.raises(HTTPException) as missing:
        asyncio.run(station.voice_say({"text": "bonjour"}))
    assert missing.value.status_code == 503
    for body in ({"text": ""}, {"text": "x" * (tts.MAX_CHARS + 1)}, {}):
        with pytest.raises(HTTPException) as bad:
            asyncio.run(station.voice_say(body))
        assert bad.value.status_code == 400


def test_status_says_whether_there_is_a_mouth():
    from server import app as station

    body = asyncio.run(station.status())
    assert set(body["mouth"]) == {"available", "voice", "error", "languages"}
    assert body["mouth"]["voice"] == tts.VOICE_NAME


@pytest.mark.skipif(not tts.SPEAKER.available(), reason="no Piper voice under models/piper")
def test_a_sentence_renders_to_real_audio_and_is_cached():
    audio = tts.SPEAKER.render("Isolement proposé pour Nils Rossi. Confirmation humaine requise.")
    assert audio[:4] == b"RIFF"
    with wave.open(io.BytesIO(audio)) as handle:
        assert handle.getnframes() / handle.getframerate() > 1.5
    assert tts.SPEAKER.render("Isolement proposé pour Nils Rossi. Confirmation humaine requise.") is audio
    assert asyncio.run(tts.SPEAKER.say("Isolement proposé pour Nils Rossi. Confirmation humaine requise.")) is audio


def test_the_voice_never_reads_numbers_off_the_screen():
    """Heard on 24 Sep: the voice read "Température 39.19 °C, SpO2 92.2 %,
    pouls 113.4 /min", and hypothesis names that sounded like a machine. The
    spoken form names the condition the way the ship's medical referent
    would, states the decision, asks the question, and carries no number."""
    from server.spoken import spoken_assessment, spoken_station_answer

    body = {
        "ok": True,
        "summary": "Température 39.19 °C, SpO2 92.2 %, pouls 113.4 /min et respiration 27.0 /min.",
        "hypotheses": [{"name": "Fièvre avec atteinte respiratoire", "supporting_signs": []},
                       {"name": "Fièvre avec désaturation", "supporting_signs": []}],
        "questions_for_patient": ["Depuis quand avez-vous de la fièvre ?"],
        "information_to_gather": ["Reprendre la saturation dans dix minutes"],
    }
    said = spoken_assessment("Ines Novak", body, {"zone": None, "confirmed": False}, "high")
    assert said.startswith("Ines Novak présente un syndrome respiratoire fébrile et de la fièvre avec un manque d’oxygène.")
    assert "J’ai décidé son isolement ; l’équipage doit en accuser réception." in said
    assert said.endswith("Question à lui poser : Depuis quand avez-vous de la fièvre ?")
    assert not any(ch.isdigit() for ch in said.split("Question")[0])
    assert len(said.split()) <= 60
    # To the person, on their own page: second person, and the decision as
    # an instruction, because the assistant is the ship's medical referent.
    mine = spoken_assessment("Eddy", body, {"zone": "A", "confirmed": True}, "high", second_person=True)
    assert mine.startswith("Eddy, vous présentez un syndrome respiratoire fébrile")
    assert "Je vous place en isolement, zone A. Restez dans vos quartiers." in mine
    assert mine.endswith("Depuis quand avez-vous de la fièvre ?")
    calm = spoken_assessment("Brad", {"ok": True, "hypotheses": [], "insufficient_data": True}, None, "routine", second_person=True)
    assert calm == "Brad, vos mesures sont dans votre plage habituelle. Rien d’inquiétant pour le moment."
    held = spoken_assessment("Ines Novak", {**body, "held_reason": "assistant_down"})
    assert held.startswith("L’assistant est arrêté ; voici sa dernière évaluation.")
    assert spoken_assessment("X", {"ok": False}) == ""
    alone = spoken_station_answer()
    assert alone.startswith("L’assistant est arrêté.") and not any(ch.isdigit() for ch in alone)
    short = spoken_station_answer("Ines Novak", 9, "haute", "isolement proposé, à confirmer par une personne")
    assert "ligne de base" not in short and len(short.split()) <= 25


def test_the_voice_introduces_itself_when_someone_switches_it_on():
    from server.speech import PHRASES

    assert PHRASES["intro"].startswith("Bonjour, je suis MedBox")
    assert "décisions médicales" in PHRASES["intro_rule"]
    for stem in ("consent_ok", "lang_fr", "wake_ack"):
        assert (ROOT / "web" / "speech" / f"{stem}.wav").is_file(), f"{stem}.wav must be rendered"
    voice = (ROOT / "web" / "voice.js").read_text(encoding="utf-8")
    assert 'say(["intro", "intro_rule"])' in voice
    for view in ("ship.js", "app.js"):
        js = (ROOT / "web" / view).read_text(encoding="utf-8")
        assert "MedBox.voice.setOn(!MedBox.voice.isOn(), true)" in js, f"{view}: the button announces, the restore does not"
        assert "MedBox.voice.setOn(MedBox.voice.restore());" in js
    for stem in ("intro", "intro_rule"):
        assert (ROOT / "web" / "speech" / f"{stem}.wav").is_file(), f"{stem}.wav must be rendered"


def test_an_assessment_response_carries_its_spoken_form(monkeypatch):
    from server import app as station

    monkeypatch.setitem(station.STATION.latest, "P-TEST", {
        "patient": {"id": "P-TEST", "name": "Test Crew"},
        "triage": {"total": 5, "urgency": "medium", "params": []},
    })
    monkeypatch.setitem(station.STATION.assessments, "P-TEST", {
        "ok": True, "patient_id": "P-TEST", "news2_at_assessment": 5, "at": __import__("time").time(),
        "summary": "Température 38.3 °C.", "hypotheses": [{"name": "Fièvre", "supporting_signs": []}],
        "questions_for_patient": [], "information_to_gather": [], "blocked": [], "insufficient_data": False,
    })
    response = asyncio.run(station.ai_assess("P-TEST"))
    body = __import__("json").loads(response.body)
    assert body["cached"] is True
    assert body["spoken"].startswith("Test Crew présente de la fièvre.")
    assert "38" not in body["spoken"]


def test_the_browser_asks_the_station_first_and_stays_guarded():
    voice = (ROOT / "web" / "voice.js").read_text(encoding="utf-8")
    assert "/api/voice/say" in voice and "localFrenchSpeech(String(text), serial, lang)" in voice
    assert "serverVoice = false" in voice, "a 503 must be remembered, not retried on every sentence"
    for view in ("ship.js", "app.js"):
        js = (ROOT / "web" / view).read_text(encoding="utf-8")
        assert re.search(r"if \(MedBox\.assessment\.spoken && MedBox\.voice\) MedBox\.voice\.speakText\(MedBox\.assessment\.spoken\(", js), (
            f"{view} must speak the assessment, guarded on the same line"
        )
    assessment = (ROOT / "web" / "assessment.js").read_text(encoding="utf-8")
    assert "spoken: spoken," in assessment
    assert "if (b.spoken) return String(b.spoken);" in assessment, "the server's spoken form wins"
