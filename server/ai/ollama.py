"""Ollama client for the slow track.

The single most important property of this module: every public call returns
either a result or None. It never raises into the caller and never blocks past
its timeout. If Ollama is missing, starting, wedged or killed live on stage,
MedBox keeps measuring and simply stops narrating.
"""
from __future__ import annotations

import json
import logging
import time

import httpx

from ..config import CONFIG
from .schemas import ASSESSMENT_SCHEMA, SYSTEM_PROMPT

log = logging.getLogger("medbox.ai")

# Built once, here, at import, before the fast track starts. Every
# httpx.AsyncClient() otherwise builds a fresh SSL context from certifi's
# bundle, synchronously, on the event loop: 600 to 1100 ms on the demo laptop,
# for a plain-http connection to localhost that never uses it. probe() runs
# every five seconds, so the board lost about ten frames every five seconds:
# the slow track stalling the fast one, which is the one thing it may not do.
# With the context passed in, making a client takes a third of a millisecond.
_TLS = httpx.create_ssl_context()


def _options() -> dict:
    """The same generation options on every call.

    Ollama reloads the model when a request asks for a different thread count
    from the one it was loaded with, so assess() and introduce() taking
    different options would pay a reload, seconds of it, each time the operator
    switched between them.
    """
    opts: dict = {"temperature": CONFIG.ai.temperature}
    if CONFIG.ai.num_thread > 0:
        opts["num_thread"] = CONFIG.ai.num_thread
    return opts


class OllamaClient:
    def __init__(self) -> None:
        self.host = CONFIG.ai.host.rstrip("/")
        self.model = CONFIG.ai.model
        self.timeout = CONFIG.ai.timeout_seconds
        self.available = False
        self.warming = False
        self.warmed = False
        self.last_error: str | None = None
        self.server_version: str | None = None
        self.last_timing: dict[str, float] = {}
        self._last_warmup_attempt = 0.0
        # True when we are talking to tools/fake_ollama.py rather than a model.
        # The station is required to say so; it must never pass a stand-in off
        # as the assistant.
        self.stand_in = False

    async def probe(self) -> bool:
        """Check Ollama is up and our model is pulled. Safe to call repeatedly."""
        try:
            async with httpx.AsyncClient(timeout=3.0, verify=_TLS) as client:
                r = await client.get(f"{self.host}/api/tags")
                r.raise_for_status()
                tags = {m.get("name", "") for m in r.json().get("models", [])}
                # Ask who we are actually talking to. The stand-in answers
                # honestly here so the interface can label itself before it
                # has shown a single assessment.
                try:
                    v = await client.get(f"{self.host}/api/version")
                    self.server_version = str(v.json().get("version", "")) or None
                    self.stand_in = "stand-in" in str(self.server_version or "").lower()
                except Exception:
                    self.server_version = None
                    self.stand_in = False
        except Exception as exc:
            self.available = False
            self.warmed = False
            self.warming = False
            self.last_error = f"{type(exc).__name__}: {exc}"
            self.stand_in = False
            return False

        # Exact tags, then the fallbacks config.toml declares, in order; a bare
        # name is Ollama's ":latest". This used to accept any tag of the same
        # family, so with only qwen2.5:0.5b pulled the indicator lit up and
        # then every question asked for 1.5b by name and got a 404, while the
        # guide promised the fallback would be used. Now it is, and
        # /api/status names the model actually answering.
        for candidate in (CONFIG.ai.model, *CONFIG.ai.fallback_models):
            if candidate in tags or f"{candidate}:latest" in tags:
                self.model = candidate
                break
        else:
            self.available = False
            self.last_error = (
                f"model {CONFIG.ai.model!r} is not pulled. Run: ollama pull {CONFIG.ai.model}"
            )
            return False

        self.available = True
        self.last_error = None
        return True

    async def warmup(self, force: bool = False) -> bool:
        """Load the selected model without delaying the measurement loop.

        A successful tags probe proves only that the daemon and manifest are
        present.  The first real generation can still spend tens of seconds
        loading weights.  This explicit warmup gives the interface a truthful
        state and keeps that cost away from the first patient interaction.
        """
        if self.warmed:
            return True
        now = time.monotonic()
        if not force and now - self._last_warmup_attempt < 60.0:
            return False
        if not self.available and not await self.probe():
            return False

        self._last_warmup_attempt = now
        self.warming = True
        body = {
            "model": self.model,
            "stream": False,
            "keep_alive": CONFIG.ai.keep_alive,
            "options": {**_options(), "num_predict": 1},
            "messages": [
                {"role": "system", "content": "Reply with one word only."},
                {"role": "user", "content": "ready"},
            ],
        }
        try:
            async with httpx.AsyncClient(
                timeout=CONFIG.ai.warmup_timeout_seconds, verify=_TLS
            ) as client:
                response = await client.post(f"{self.host}/api/chat", json=body)
                response.raise_for_status()
                payload = response.json()
            self.last_timing = {
                key: round(float(payload.get(key, 0)) / 1_000_000_000, 3)
                for key in ("total_duration", "load_duration", "prompt_eval_duration", "eval_duration")
                if payload.get(key) is not None
            }
            self.warmed = True
            self.available = True
            self.last_error = None
            return True
        except Exception as exc:
            self.warmed = False
            self.last_error = f"warmup {type(exc).__name__}: {exc}"
            log.warning("AI warmup failed; deterministic station remains live: %s", exc)
            return False
        finally:
            self.warming = False

    async def assess(self, patient: dict, triage: dict, history_note: str = "") -> dict | None:
        """Ask for hypotheses. Returns None on any failure, never raises."""
        # Hand over the reason the band is what it is, not just the number.
        # Under NEWS2 a single parameter scoring 3 escalates on its own, so an
        # aggregate of 3 can be MEDIUM. A model given the bare pair sees a small
        # number beside a serious word, resolves the tension in favour of the
        # number, and writes "reassuring" directly under a MEDIUM band.
        why_band = ""
        if triage.get("single_param_3"):
            param = triage.get("worst_param") or "one parameter"
            why_band = (
                f"This band was set by the NEWS2 single-parameter rule: {param} alone "
                f"scored 3, which escalates on its own whatever the aggregate is. Do "
                f"not describe this aggregate as low or reassuring.\n"
            )
        prompt = (
            f"Crew member {patient.get('name')} ({patient.get('role')}), id {patient.get('id')}.\n\n"
            f"Current readings:\n"
            f"  temperature  {patient.get('temperature')} C\n"
            f"  SpO2         {patient.get('spo2')} %\n"
            f"  pulse        {patient.get('pulse')} /min\n"
            f"  respiration  {patient.get('respiration')} /min\n\n"
            f"NEWS2 aggregate {triage.get('total')} -> urgency '{triage.get('urgency')}'.\n"
            f"{why_band}"
            f"Parameters actually measured: {', '.join(triage.get('measured', []))}.\n"
            f"{history_note}\n\n"
            "Give your assessment."
        )
        body = {
            "model": self.model,
            "stream": False,
            "format": ASSESSMENT_SCHEMA,
            # Without keep_alive the first question after an idle gap spends
            # five to fifteen seconds loading the weights off disk, which on
            # stage looks exactly like a crash.
            "keep_alive": CONFIG.ai.keep_alive,
            "options": _options(),
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout, verify=_TLS) as client:
                r = await client.post(f"{self.host}/api/chat", json=body)
                r.raise_for_status()
                payload = r.json()
                content = payload.get("message", {}).get("content", "")
            self.warmed = True
            self.last_timing = {
                key: round(float(payload.get(key, 0)) / 1_000_000_000, 3)
                for key in ("total_duration", "load_duration", "prompt_eval_duration", "eval_duration")
                if payload.get(key) is not None
            }
            return json.loads(content)
        except Exception as exc:
            # Expected during the demo when Ollama is killed on purpose.
            log.warning("AI unavailable, continuing without narration: %s", exc)
            self.available = False
            self.warmed = False
            self.last_error = f"{type(exc).__name__}: {exc}"
            return None


    async def introduce(self) -> str | None:
        """Return a complete French orientation with a tightly bounded AI greeting.

        This deliberately has no `prompt` parameter. An earlier version was
        `freeform(prompt: str)`, which meant the codebase contained a path that
        prepended the full system prompt to arbitrary text and ran it with no
        schema at all. Nothing used it that way, and the safety argument
        everywhere else in this project is "there is no diagnosis field in the
        shape it is allowed to answer in" — which is worth nothing next to a
        path where there is no shape. Only convention kept it pointed
        somewhere harmless, and the twenty minutes before a jury demo is
        exactly when someone wires a text box into a convenient helper.

        So the prompt is built inside. There is no argument to pass, and
        tests/test_ai_path.py asserts there never is again.

        Operational claims, safety limits and the explicit continuous-listening
        consent question are deterministic. Ollama supplies at most one short
        greeting; if it is slow, absent or produces anything outside that narrow
        shape, the station uses a fixed greeting and still completes immediately.
        """
        from .capabilities import deterministic_introduction, self_explanation_prompt

        prompt = self_explanation_prompt()
        body = {
            "model": self.model,
            "stream": False,
            "keep_alive": CONFIG.ai.keep_alive,
            # The model contributes one greeting only. The reviewed capability,
            # safety and consent text is appended by the station below. Sixteen
            # tokens measured comfortably below the stage timeout on the demo PC.
            "options": {**_options(), "num_predict": 16},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Vous êtes MedBox. Répondez uniquement en français, en une "
                        "courte salutation. Aucun conseil médical."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout, verify=_TLS) as client:
                r = await client.post(f"{self.host}/api/chat", json=body)
                r.raise_for_status()
                payload = r.json()
                text = payload.get("message", {}).get("content", "")
            self.last_timing = {
                key: round(float(payload.get(key, 0)) / 1_000_000_000, 3)
                for key in ("total_duration", "load_duration", "prompt_eval_duration", "eval_duration")
                if payload.get(key) is not None
            }
            self.warmed = True
        except Exception as exc:
            log.warning("AI greeting unavailable; using deterministic introduction: %s", exc)
            self.available = False
            self.warmed = False
            self.last_error = f"{type(exc).__name__}: {exc}"
            return deterministic_introduction()

        greeting = " ".join((text or "").strip().split())
        lowered = greeting.casefold()
        safe_shape = (
            4 <= len(greeting.split()) <= 14
            and len(greeting) <= 120
            and "medbox" in lowered
            and not any(char.isdigit() for char in greeting)
            and not any(
                token in lowered
                for token in (
                    "diagnost", "prescri", "médicament", "medicament", "dose",
                    "traitement", "urgence", "isolez", "prenez", "administrez",
                )
            )
        )
        if not safe_shape or self.stand_in:
            greeting = "Bonjour, je suis MedBox."
        elif greeting[-1] not in ".!?":
            greeting += "."
        self.last_error = None
        return deterministic_introduction(greeting)


CLIENT = OllamaClient()
