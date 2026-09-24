"""The station's voice for words nobody pre-recorded: the assistant's own.

Slow track. Nothing in `triage`, `sensors`, `db` or `quarantine` imports this,
and the board is drawn whether or not a voice exists. Piper renders a French
sentence in under a second on the demo CPU (measured 0.75 s for fourteen
words, 3.7 s to load the voice once), in a worker thread so the ten-hertz
feed never waits on it.

The voice is optional in exactly the way the microphone is: absent, the
station says so in `/api/status`, `/api/voice/say` answers 503, and the
browser falls back to the pre-rendered clips, silent for free text, which is
what it did before this file existed. The clips are still the ship's
announcements, written by the team; this voice only reads what the model
wrote after the validator rebuilt it.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import re
import threading
import wave
from collections import OrderedDict
from pathlib import Path

from .config import ROOT

log = logging.getLogger("medbox.tts")

VOICE_NAME = "fr_FR-siwis-medium"
VOICE_DIR = ROOT / "models" / "piper"
VOICES = {"fr": "fr_FR-siwis-medium", "en": "en_US-lessac-medium"}
MAX_CHARS = 400
CACHE_SIZE = 64

# What the voice would misread. The clip renderer learned the first one by
# transcribing its own output back; the rest are how a French clinician says
# a unit out loud rather than how a screen prints it.
SPOKEN = (
    (re.compile(r"\bMedBox\b"), "Med Box"),
    (re.compile(r"\bNEWS2\b"), "score d’alerte"),
    (re.compile(r"\bSpO2\b", re.I), "saturation"),
    (re.compile(r"(\d)\.(\d)"), r"\1,\2"),
    (re.compile(r"\s*°\s*C\b"), " degrés"),
    (re.compile(r"\s*%"), " pour cent"),
    (re.compile(r"\s*/\s*min\b"), " par minute"),
    (re.compile(r"\s*mmHg\b"), " millimètres de mercure"),
    (re.compile(r"\bACVPU\b"), "échelle de conscience"),
)


SPOKEN_EN = (
    (re.compile(r"\bMedBox\b"), "Med Box"),
    (re.compile(r"\bSpO2\b", re.I), "oxygen saturation"),
    (re.compile(r"\s*°\s*C\b"), " degrees"),
    (re.compile(r"\s*%"), " percent"),
    (re.compile(r"\s*/\s*min\b"), " per minute"),
    (re.compile(r"\s*mmHg\b"), " millimetres of mercury"),
)


def normalise(text: str, lang: str = "fr") -> str:
    """One line of plain speech the voice can say, from what the screen shows."""
    out = " ".join(str(text or "").split())
    for pattern, spoken in (SPOKEN_EN if lang == "en" else SPOKEN):
        out = pattern.sub(spoken, out)
    return out.strip()[:MAX_CHARS]


class Speaker:
    """One Piper voice, loaded on first use, rendering one sentence at a time."""

    def __init__(self, model_path: Path | None = None, lang: str = "fr") -> None:
        self.lang = lang
        self.model_path = Path(model_path) if model_path else VOICE_DIR / f"{VOICES.get(lang, VOICE_NAME)}.onnx"
        self.last_error: str | None = None
        self._voice = None
        self._lock = threading.Lock()
        self._cache: OrderedDict[str, bytes] = OrderedDict()

    def available(self) -> bool:
        return self.model_path.is_file() and self.model_path.with_suffix(".onnx.json").is_file()

    def _load(self):
        if self._voice is None:
            from piper import PiperVoice  # the only import of the engine; optional dependency

            self._voice = PiperVoice.load(str(self.model_path))
        return self._voice

    def render(self, text: str) -> bytes:
        """WAV bytes for `text`. Raises RuntimeError when there is no voice."""
        spoken = normalise(text, self.lang)
        if not spoken:
            raise ValueError("nothing to say")
        if not self.available():
            self.last_error = f"aucune voix sous {self.model_path.parent}"
            raise RuntimeError(self.last_error)
        key = hashlib.sha1(spoken.encode("utf-8")).hexdigest()
        with self._lock:
            hit = self._cache.get(key)
            if hit is not None:
                self._cache.move_to_end(key)
                return hit
            try:
                voice = self._load()
                buffer = io.BytesIO()
                with wave.open(buffer, "wb") as handle:
                    voice.synthesize_wav(spoken, handle)
            except Exception as exc:  # the engine's own failures, reported not raised further up
                self.last_error = f"{type(exc).__name__}: {exc}"
                log.warning("voice could not render %r: %s", spoken[:60], exc)
                raise RuntimeError(self.last_error) from exc
            audio = buffer.getvalue()
            self._cache[key] = audio
            while len(self._cache) > CACHE_SIZE:
                self._cache.popitem(last=False)
            self.last_error = None
            return audio

    async def say(self, text: str) -> bytes:
        """`render`, off the event loop: the board keeps its ten frames a second."""
        return await asyncio.to_thread(self.render, text)


SPEAKER = Speaker(lang="fr")
SPEAKERS = {"fr": SPEAKER, "en": Speaker(lang="en")}


def speaker_for(lang: str) -> Speaker:
    """The voice for a language code; French for anything it does not have."""
    return SPEAKERS.get(str(lang or "fr").lower()[:2], SPEAKER)
