"""The slow track, end to end, without a language model.

These tests exercise the real OllamaClient against tools/fake_ollama.py. They
prove the things that actually break in integration — the probe, the schema
round trip, the stand-in disclosure, and above all the promise that a dead AI
never raises into the caller — without needing four gigabytes of weights on
the machine running them.

What they deliberately do NOT test is whether the model is any good. Nothing
here says anything about the quality of an assessment.
"""
from __future__ import annotations

import asyncio
import socket
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.ai.ollama import OllamaClient  # noqa: E402
from tools.fake_ollama import serve  # noqa: E402

PATIENT = {
    "id": "P-04",
    "name": "Ines Novak",
    "role": "Systems",
    "temperature": 39.1,
    "spo2": 92.0,
    "pulse": 118.0,
    "respiration": 25.0,
}
TRIAGE = {"total": 9, "urgency": "high",
          "measured": ["temperature", "spo2", "pulse", "respiration"]}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def stand_in():
    port = _free_port()
    httpd = serve(port=port)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        httpd.shutdown()


def _client(host: str) -> OllamaClient:
    c = OllamaClient()
    c.host = host
    return c


def test_probe_finds_the_model_and_flags_the_stand_in(stand_in):
    c = _client(stand_in)
    assert asyncio.run(c.probe()) is True
    assert c.available is True
    assert c.last_error is None
    # The station must know it is not talking to a model, so the interface
    # can say so before it shows anything.
    assert c.stand_in is True


def test_assessment_round_trips_the_schema(stand_in):
    c = _client(stand_in)
    asyncio.run(c.probe())
    result = asyncio.run(c.assess(PATIENT, TRIAGE))
    assert result is not None
    for field in ("summary", "hypotheses", "questions_for_patient",
                  "suggested_protocol", "escalate"):
        assert field in result, f"{field} missing from the assessment"
    assert isinstance(result["hypotheses"], list) and result["hypotheses"]
    for h in result["hypotheses"]:
        assert h["confidence"] in ("low", "moderate", "high")
        assert h["supporting_signs"], "a hypothesis with no supporting sign is a guess"


def test_assessment_never_contains_a_diagnosis_field(stand_in):
    """The absence of this field is the whole safety argument. Guard it."""
    c = _client(stand_in)
    asyncio.run(c.probe())
    result = asyncio.run(c.assess(PATIENT, TRIAGE))
    assert "diagnosis" not in result
    assert "diagnoses" not in result


def test_a_dead_ai_returns_none_and_never_raises():
    """The demo kills Ollama live on stage. This is that moment, in a test."""
    c = _client(f"http://127.0.0.1:{_free_port()}")   # nothing is listening
    assert asyncio.run(c.probe()) is False
    assert c.available is False
    assert c.stand_in is False
    assert asyncio.run(c.assess(PATIENT, TRIAGE)) is None   # no exception


def test_every_supporting_sign_names_a_measurement(stand_in):
    """A claim that cites no instrument is exactly what this project forbids."""
    c = _client(stand_in)
    asyncio.run(c.probe())
    result = asyncio.run(c.assess(PATIENT, TRIAGE))
    instruments = ("temperature", "spo2", "pulse", "respiration", "parameters")
    for h in result["hypotheses"]:
        for sign in h["supporting_signs"]:
            assert any(word in sign.lower() for word in instruments), (
                f"supporting sign cites no measurement: {sign!r}"
            )
