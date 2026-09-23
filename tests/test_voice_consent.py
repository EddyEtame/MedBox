"""Consent is a gate, not a symptom, and listening stays local."""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _node(expression: str) -> object:
    mic = json.dumps(str(ROOT / "web" / "mic.js"))
    source = (
        "const fs=require('fs');global.window=global;global.navigator={};"
        f"eval(fs.readFileSync({mic},'utf8'));"
        f"process.stdout.write(JSON.stringify({expression}));"
    )
    result = subprocess.run(
        ["node", "-e", source], capture_output=True, text=True, check=True, timeout=10
    )
    return json.loads(result.stdout)


def test_only_the_four_explicit_positive_consent_phrases_open_the_gate():
    cases = [
        "J'accepte",
        "j’accepte",
        "Oui.",
        "I accept",
        "yes",
        "Je n'accepte pas",
        "non",
        "I do not accept",
        "je n'ai pas dit oui",
        "the word yes",
        "peut-être",
    ]
    assert _node("%s.map(MedBox.mic.consentDecision)" % json.dumps(cases)) == [
        "accept", "accept", "accept", "accept", "accept",
        "reject", "reject", "reject", "unknown", "unknown", "unknown",
    ]


def test_wake_word_is_required_as_a_word_not_a_substring():
    cases = ["MedBox", "med box, j'ai froid", "MED-BOX help", "premedbox", "docteur"]
    assert _node("%s.map(MedBox.mic.hasWakeWord)" % json.dumps(cases)) == [
        True, True, True, False, False
    ]


def test_browser_flow_names_every_visible_state_and_never_uses_cloud_recognition():
    source = (ROOT / "web" / "mic.js").read_text(encoding="utf-8")
    for state in (
        "ARRÊTÉ", "ACTIVATION", "CONSENTEMENT", "À L’ÉCOUTE",
        "PAROLE DÉTECTÉE", "TRANSCRIPTION", "MEDBOX ACTIVÉ", "EN PAUSE", "ERREUR",
    ):
        assert state in source
    for phrase in ("J’accepte", "oui", "I accept", "yes"):
        assert phrase in source
    assert "getUserMedia" in source
    assert "MIN_CONSENT_CONFIDENCE" in source
    assert "webkitSpeechRecognition" not in source
    assert "SpeechRecognition(" not in source
    assert 'fetch("/api/voice/transcribe"' in source
    assert "sessionStorage" not in source and "localStorage" not in source


def test_transcriber_auto_detects_french_or_english_and_keeps_vad(tmp_path):
    from server.voice import Transcriber

    captured: dict = {}

    class Model:
        def transcribe(self, path, **kwargs):
            captured.update(kwargs)
            segment = SimpleNamespace(text=" J'ai froid ", avg_logprob=-0.1)
            return [segment], SimpleNamespace(language="fr")

    transcriber = Transcriber(tmp_path)
    transcriber._model = Model()
    result = transcriber._transcribe(tmp_path / "phrase.webm")
    assert result is not None
    text, confidence, language = result
    assert text == "J'ai froid"
    assert 0 < confidence <= 1
    assert language == "fr"
    assert "language" not in captured, "a fixed language disables bilingual detection"
    assert captured["vad_filter"] is True
    assert "J'accepte" in captured["initial_prompt"]
    assert "Je n'accepte pas" in captured["initial_prompt"]
    assert "I accept" in captured["initial_prompt"]
    assert "I do not accept" in captured["initial_prompt"]


def test_non_persisting_route_returns_language_and_never_writes_a_symptom(monkeypatch):
    import server.app as app

    async def heard(_request):
        return "J'accepte", 0.91, "fr"

    def forbidden(*_args, **_kwargs):
        raise AssertionError("consent must never be filed as a symptom")

    monkeypatch.setattr(app, "_transcribe_audio", heard)
    monkeypatch.setattr(app.STATION.symptoms, "add", forbidden)
    response = asyncio.run(app.transcribe_voice(object()))
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert json.loads(response.body) == {
        "heard": {"text": "J'accepte", "confidence": 0.91, "language": "fr"}
    }


def test_uploaded_audio_is_deleted_even_after_local_transcription(tmp_path, monkeypatch):
    import server.app as app

    class Request:
        async def body(self):
            return b"not-real-audio"

    seen: list[Path] = []

    async def listen(path: Path):
        seen.append(path)
        assert path.exists()
        return "oui", 0.8, "fr"

    monkeypatch.setattr(app.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(app.TRANSCRIBER, "listen", listen)
    assert asyncio.run(app._transcribe_audio(Request())) == ("oui", 0.8, "fr")
    assert len(seen) == 1
    assert not seen[0].exists()
    assert list(tmp_path.iterdir()) == []
