"""Turning what a crew member said into text, without ever blocking a reading.

This is a slow track, and it obeys the same rule the assistant does: it may
fail, it may be absent, it may take four seconds, and none of that is allowed
to touch a measurement. If Whisper is not installed, or the weights were never
copied onto this machine, the microphone button simply says so and typing
still works.

Two decisions worth the words.

**A transcript is a guess, and the interface has to show that.** `symptoms.py`
has carried a `confidence` field and a `"voice"` source since before anything
could produce them, for exactly this moment. An operator acting on a misheard
symptom should be able to see that it was misheard, so the confidence travels
all the way to the screen and is never rounded away. This matters more here
than in most products: the whole project rests on the difference between what
was measured and what was claimed, and a transcript is a claim about a claim.

**It runs in a thread, not a subprocess and not on the event loop.** On the
event loop it would stall the ten-hertz board for as long as it took, which is
the one thing this architecture forbids. As a subprocess it would be more
isolated but would also, on Windows, re-import `server/app.py` under spawn and
re-run `STATION = MedBox()` — a second station, a second database handle, and
a very confusing afternoon. A thread avoids both, and it is genuinely parallel
here because CTranslate2 releases the GIL while it works.

The weights are loaded from a local directory and never fetched. That is not
paranoia about the network, it is the standalone claim: `huggingface_hub` must
not be reached at runtime, on a ship or in a lecture theatre.
"""
from __future__ import annotations

import asyncio
import logging
import math
from pathlib import Path

from .config import CONFIG, ROOT, python_command

log = logging.getLogger("medbox.voice")

# Where the converted model directory lives. Kept out of git: it is far past
# GitHub's blob limit, and tools/assets.py is how it reaches a machine.
MODEL_DIR = ROOT / "models" / "faster-whisper-base"

# What a loadable model directory actually holds. Taken from faster-whisper's
# own `allow_patterns`, which is the only place this list is authoritative.
#
# Checking the files rather than just the directory matters more than it looks.
# A half-copied model off a USB stick leaves a directory that exists, so the
# microphone button would appear and then fail on the first press — which is
# the thing this whole property is meant to prevent. tools/assets.py checks the
# same three names, so the installer and the server agree on what "present"
# means.
MODEL_FILES = ("config.json", "model.bin", "tokenizer.json")


class Transcriber:
    """Loads once, lazily, and reports honestly when it cannot."""

    def __init__(self, model_dir: Path = MODEL_DIR) -> None:
        self.model_dir = model_dir
        self._model = None
        self._tried = False
        self.last_error: str | None = None

    def _where(self) -> str:
        """The model directory, said the way a person would read it.

        Relative to the repo when it is inside it, absolute when it is not.
        `relative_to` raises on a path outside the root, and this is reached
        from `available`, which the board calls ten times a second — a property
        on that path is not allowed to raise for a cosmetic reason.
        """
        try:
            return str(self.model_dir.relative_to(ROOT))
        except ValueError:
            return str(self.model_dir)

    @property
    def available(self) -> bool:
        """Can this machine transcribe at all?

        Answered without loading anything, because the interface asks on every
        status frame and the answer decides whether a microphone button is
        shown. A button that appears and then fails is worse than no button.
        """
        if self._model is not None:
            return True
        if not self.model_dir.is_dir():
            self.last_error = (
                f"no speech model at {self._where()}. "
                f"Run: {python_command('tools/assets.py')}"
            )
            return False
        short = [f for f in MODEL_FILES if not (self.model_dir / f).exists()]
        if short:
            self.last_error = (
                f"the speech model at {self._where()} is "
                f"incomplete ({', '.join(short)} missing). "
                f"Run: {python_command('tools/assets.py')}"
            )
            return False
        try:
            import faster_whisper  # noqa: F401
        except Exception as exc:
            self.last_error = f"faster-whisper is not installed ({type(exc).__name__})"
            return False
        self.last_error = None
        return True

    def _load(self):
        if self._model is not None or self._tried:
            return self._model
        self._tried = True
        try:
            from faster_whisper import WhisperModel

            # By path, never by name: a bare name sends faster-whisper to
            # Hugging Face, and the one thing this product promises is that it
            # does not need the network.
            self._model = WhisperModel(
                str(self.model_dir), device="cpu", compute_type="int8"
            )
            self.last_error = None
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            log.warning("speech model would not load: %s", exc)
        return self._model

    def _transcribe(self, path: Path) -> tuple[str, float, str | None] | None:
        model = self._load()
        if model is None:
            return None
        try:
            # Do not pin this to English. The station is presented in French,
            # but a crew member may answer in either French or English. A
            # missing ``language`` argument makes Whisper detect it locally
            # for each utterance. The short prompt only helps it keep the
            # product name and the four explicit consent phrases intact; it
            # is not retained and it is never sent anywhere.
            segments, info = model.transcribe(
                str(path),
                beam_size=1,          # one beam: this is a short phrase, not prose
                vad_filter=True,      # drop the silence either side of the press
                condition_on_previous_text=False,
                initial_prompt=(
                    "MedBox. Français et English. J'accepte. Je n'accepte pas. "
                    "Oui. Non. I accept. I do not accept. Yes. No."
                ),
            )
            parts, logprobs = [], []
            for seg in segments:
                text = (seg.text or "").strip()
                if text:
                    parts.append(text)
                    logprobs.append(seg.avg_logprob)
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            log.warning("transcription failed: %s", exc)
            return None

        said = " ".join(parts).strip()
        if not said:
            return None
        # Whisper reports an average log probability per segment. Turning it
        # into a 0-1 number is a presentation choice, not a measurement, and it
        # is labelled on screen as "sure" rather than as anything clinical.
        mean = sum(logprobs) / len(logprobs) if logprobs else -1.0
        language = getattr(info, "language", None)
        if language is not None:
            language = str(language).lower()
        return said, max(0.0, min(1.0, math.exp(mean))), language

    async def listen(self, path: Path) -> tuple[str, float, str | None] | None:
        """Transcribe a recording. Returns None on any failure, never raises.

        The same contract as the Ollama client, for the same reason: everything
        on the slow track has to be safe to lose.
        """
        if not self.available:
            return None
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._transcribe, path),
                timeout=CONFIG.ai.timeout_seconds,
            )
        except asyncio.TimeoutError:
            self.last_error = "transcription took too long and was abandoned"
            log.warning("transcription timed out")
            return None
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return None


TRANSCRIBER = Transcriber()
