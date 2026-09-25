"""The voice and the ears, measured 24 Sep on the defence laptop: a fresh
sentence cost 0.4 to 1.9 s of synthesis before the first sound, the ears
0.9 s to load on the first spoken word. So the client speaks sentence by
sentence and fetches the next while one plays, rendered sentences live on
disk across launches, the fixed sentences are rendered at start-up, the
ears are loaded at start-up, and the voice reads a little more briskly.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_the_client_speaks_sentence_by_sentence():
    src = (ROOT / "web" / "voice.js").read_text(encoding="utf-8")
    assert "function sentencesOf(text)" in src and "function fetchClip(text, lang)" in src
    body = src[src.index("function serverSpeech(text, serial, lang)"):]
    body = body[:body.index("function speakText")]
    assert "sentencesOf(text)" in body and "next = fetchClip(parts[i], lang)" in body, "prefetch the next sentence while one plays"


def test_rendered_sentences_outlive_the_process(tmp_path, monkeypatch):
    from server import tts
    monkeypatch.setattr(tts, "DISK_CACHE", tmp_path)
    spoken = tts.normalise("Personne n’est en isolement.", "fr")
    assert spoken
    src = (ROOT / "server" / "tts.py").read_text(encoding="utf-8")
    assert "on_disk.write_bytes(audio)" in src and "on_disk.read_bytes()" in src
    assert "SynthesisConfig(length_scale=LENGTH_SCALE)" in src and 0.8 <= tts.LENGTH_SCALE < 1.0


def test_the_station_warms_voice_and_ears_at_start():
    src = (ROOT / "server" / "app.py").read_text(encoding="utf-8")
    assert "warm_voice_and_ears" in src and "SPEAKER.warm, FIXED_SENTENCES" in src and "TRANSCRIBER._load" in src
    import server.app as station
    assert station.INTRO_SPOKEN in station.FIXED_SENTENCES
    assert any("Un instant" in s for s in station.FIXED_SENTENCES)
    ears = (ROOT / "server" / "voice.py").read_text(encoding="utf-8")
    assert "cpu_threads=4" in ears, "four threads: the model keeps the rest of the processor"


def test_every_header_is_a_bar():
    css = (ROOT / "web" / "style.css").read_text(encoding="utf-8")
    assert "header,.bar{" in css, "the crew and personal pages write a bare <header>"
    assert "max-width:1560px" in css, "a projector at 1920 gets a ceiling, not a sprawl"
    assert "padding:16px 20px 120px" in css, "room under the content for the listening pill"
