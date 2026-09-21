"""Ollama client for the slow track.

The single most important property of this module: every public call returns
either a result or None. It never raises into the caller and never blocks past
its timeout. If Ollama is missing, starting, wedged or killed live on stage,
MedBox keeps measuring and simply stops narrating.
"""
from __future__ import annotations

import json
import logging

import httpx

from ..config import CONFIG
from .schemas import ASSESSMENT_SCHEMA, SYSTEM_PROMPT

log = logging.getLogger("medbox.ai")


class OllamaClient:
    def __init__(self) -> None:
        self.host = CONFIG.ai.host.rstrip("/")
        self.model = CONFIG.ai.model
        self.timeout = CONFIG.ai.timeout_seconds
        self.available = False
        self.last_error: str | None = None

    async def probe(self) -> bool:
        """Check Ollama is up and our model is pulled. Safe to call repeatedly."""
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                r = await client.get(f"{self.host}/api/tags")
                r.raise_for_status()
                tags = {m.get("name", "") for m in r.json().get("models", [])}
        except Exception as exc:
            self.available = False
            self.last_error = f"{type(exc).__name__}: {exc}"
            return False

        # Ollama reports "qwen2.5:3b-instruct"; accept a bare name too.
        wanted = self.model.split(":")[0]
        if not any(t == self.model or t.split(":")[0] == wanted for t in tags):
            self.available = False
            self.last_error = (
                f"model {self.model!r} is not pulled. Run: ollama pull {self.model}"
            )
            return False

        self.available = True
        self.last_error = None
        return True

    async def assess(self, patient: dict, triage: dict, history_note: str = "") -> dict | None:
        """Ask for hypotheses. Returns None on any failure, never raises."""
        prompt = (
            f"Crew member {patient.get('name')} ({patient.get('role')}), id {patient.get('id')}.\n\n"
            f"Current readings:\n"
            f"  temperature  {patient.get('temperature')} C\n"
            f"  SpO2         {patient.get('spo2')} %\n"
            f"  pulse        {patient.get('pulse')} /min\n"
            f"  respiration  {patient.get('respiration')} /min\n\n"
            f"NEWS2 aggregate {triage.get('total')} -> urgency '{triage.get('urgency')}'.\n"
            f"Parameters actually measured: {', '.join(triage.get('measured', []))}.\n"
            f"{history_note}\n\n"
            "Give your assessment."
        )
        body = {
            "model": self.model,
            "stream": False,
            "format": ASSESSMENT_SCHEMA,
            "options": {"temperature": CONFIG.ai.temperature},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.post(f"{self.host}/api/chat", json=body)
                r.raise_for_status()
                content = r.json().get("message", {}).get("content", "")
            return json.loads(content)
        except Exception as exc:
            # Expected during the demo when Ollama is killed on purpose.
            log.warning("AI unavailable, continuing without narration: %s", exc)
            self.available = False
            self.last_error = f"{type(exc).__name__}: {exc}"
            return None


CLIENT = OllamaClient()
