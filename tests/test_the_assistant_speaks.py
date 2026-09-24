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

    monkeypatch.setattr(station, "SPEAKER", tts.Speaker(tmp_path / "nowhere.onnx"))
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
    assert set(body["mouth"]) == {"available", "voice", "error"}
    assert body["mouth"]["voice"] == tts.VOICE_NAME


@pytest.mark.skipif(not tts.SPEAKER.available(), reason="no Piper voice under models/piper")
def test_a_sentence_renders_to_real_audio_and_is_cached():
    audio = tts.SPEAKER.render("Isolement proposé pour Nils Rossi. Confirmation humaine requise.")
    assert audio[:4] == b"RIFF"
    with wave.open(io.BytesIO(audio)) as handle:
        assert handle.getnframes() / handle.getframerate() > 1.5
    assert tts.SPEAKER.render("Isolement proposé pour Nils Rossi. Confirmation humaine requise.") is audio
    assert asyncio.run(tts.SPEAKER.say("Isolement proposé pour Nils Rossi. Confirmation humaine requise.")) is audio


def test_the_browser_asks_the_station_first_and_stays_guarded():
    voice = (ROOT / "web" / "voice.js").read_text(encoding="utf-8")
    assert "/api/voice/say" in voice and "localFrenchSpeech(String(text), serial)" in voice
    assert "serverVoice = false" in voice, "a 503 must be remembered, not retried on every sentence"
    for view in ("ship.js", "app.js"):
        js = (ROOT / "web" / view).read_text(encoding="utf-8")
        assert re.search(r"if \(MedBox\.assessment\.spoken && MedBox\.voice\) MedBox\.voice\.speakText\(MedBox\.assessment\.spoken\(", js), (
            f"{view} must speak the assessment, guarded on the same line"
        )
    assessment = (ROOT / "web" / "assessment.js").read_text(encoding="utf-8")
    assert "spoken: spoken," in assessment
