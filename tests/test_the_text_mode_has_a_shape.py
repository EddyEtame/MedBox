"""The text mode is a typed question answered under a shape, never free prose.

`tests/test_ai_path.py` pins that no method runs caller text with no schema.
This file pins the one method that takes caller text: it decodes under
ANSWER_SCHEMA, under the same system prompt as an assessment, and its output
is rebuilt by `enforce_answer` before a panel or a voice gets it. When the
model is absent the station answers with its own facts and says so.
"""
from __future__ import annotations

import asyncio
import inspect
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server import app as station  # noqa: E402
from server.ai.ollama import OllamaClient  # noqa: E402
from server.ai.schemas import ANSWER_SCHEMA, MAX_ANSWER_CHARS  # noqa: E402
from server.ai.validate import NO_ANSWER, SUPPRESSED_ANSWER, enforce_answer  # noqa: E402


def test_the_question_path_always_sends_a_shape():
    assert list(inspect.signature(OllamaClient.answer).parameters) == ["self", "question", "facts"]
    src = inspect.getsource(OllamaClient.answer)
    # 24 Sep: the JSON shape cost a dozen of thirty tokens at seven tokens a
    # second on the defence laptop; a question is now plain text, one line,
    # and the station grounds it itself (app._ungrounded). ANSWER_SCHEMA
    # remains the shape enforce_answer reads.
    assert '"stop": ["\\n"]' in src and '"num_predict": 26' in src, "one sentence, stopped at the line break"
    assert '{"role": "system", "content": SYSTEM_PROMPT}' in src, "same prompt as an assessment, or the cache is evicted"


def test_the_shape_has_no_room_for_a_diagnosis_or_an_urgency():
    assert set(ANSWER_SCHEMA["properties"]) == {"answer", "grounded_in"}
    assert ANSWER_SCHEMA["additionalProperties"] is False
    assert ANSWER_SCHEMA["properties"]["answer"]["maxLength"] == MAX_ANSWER_CHARS <= 280
    assert ANSWER_SCHEMA["properties"]["grounded_in"]["enum"] == ["measurements", "manual", "nothing"]


@pytest.mark.parametrize("text", [
    "Prenez 500 mg de paracétamol toutes les six heures.",
    "Administrez de l’oxygène par voie nasale.",
])
def test_a_prescription_in_the_answer_is_replaced_and_said(text):
    out = enforce_answer({"answer": text, "grounded_in": "manual"})
    assert out["answer"] == NO_ANSWER and out["grounded_in"] == "nothing"
    assert out["blocked"] == [SUPPRESSED_ANSWER]


def test_the_referent_may_name_a_condition_but_never_a_drug():
    """Since 24 Sep the assistant is the ship's medical referent: it says what
    a person has. The drug line stays closed."""
    said = enforce_answer({"answer": "Vous présentez un syndrome respiratoire fébrile, compatible avec l’exposition à bord.", "grounded_in": "measurements"})
    assert said["blocked"] == [] and "syndrome respiratoire" in said["answer"]


def test_a_plain_answer_passes_and_a_long_one_is_cut_on_a_word():
    out = enforce_answer({"answer": "Le score vient de la respiration à 25 par minute et de la température.", "grounded_in": "measurements"})
    assert out == {"ok": True, "answer": "Le score vient de la respiration à 25 par minute et de la température.",
                   "grounded_in": "measurements", "blocked": []}
    long = enforce_answer({"answer": "mot " * 200, "grounded_in": "manual"})
    assert long["answer"].endswith("…") and len(long["answer"]) <= MAX_ANSWER_CHARS + 1


def test_garbage_and_an_unknown_source_get_the_station_sentence():
    assert enforce_answer("nope")["answer"] == NO_ANSWER
    assert enforce_answer("nope")["ok"] is False
    out = enforce_answer({"answer": "", "grounded_in": "cloud"})
    assert out["answer"] == NO_ANSWER and out["grounded_in"] == "nothing"


def test_the_facts_are_written_by_the_station():
    facts, own, spoken = station._facts_for(None)
    assert "NEWS2" in facts and "référent médical du bord" in facts
    assert "Ce que la station sait faire" in facts
    # The crew's state is in the facts, and the station's own sentence is
    # about the crew; the reason (down, late, ungrounded) is added by the route.
    assert "Équipage :" in facts and "Ne citez que ces noms" in facts
    assert not own.startswith("L’assistant est arrêté") and "isolement" in own
    assert not spoken.startswith("L’assistant est arrêté") and len(spoken.split()) <= 40


def test_without_the_model_the_station_answers_itself(monkeypatch):
    monkeypatch.setattr(station.CLIENT, "available", False)
    out = asyncio.run(station.assistant_ask({"text": "Que mesure MedBox ?"}))
    assert out["held_reason"] == "assistant_down" and out["grounded_in"] == "manual"
    assert out["answer"].startswith(station.DOWN) and "isolement" in out["answer"]
    # The voice gets the short form, never the fact sheet with the baselines.
    assert "ligne de base" not in out["spoken"] and len(out["spoken"].split()) <= 45


def test_the_model_answer_passes_the_validator_before_anyone_reads_it(monkeypatch):
    monkeypatch.setattr(station.CLIENT, "available", True)

    async def prescribes(question, facts):
        assert "Question de l’opérateur" not in facts, "the facts are the station's, the question is separate"
        return {"answer": "Donnez 1 g de paracétamol.", "grounded_in": "manual"}

    monkeypatch.setattr(station.CLIENT, "answer", prescribes)
    out = asyncio.run(station.assistant_ask({"text": "Que faire ?"}))
    assert out["answer"] == NO_ANSWER and out["blocked"] == [SUPPRESSED_ANSWER]
    assert out["held_reason"] is None
    assert out["spoken"] == out["answer"], "the voice reads the validated answer, nothing else"


def test_a_silent_model_yields_the_station_sentence(monkeypatch):
    monkeypatch.setattr(station.CLIENT, "available", True)

    async def silent(question, facts):
        return None

    monkeypatch.setattr(station.CLIENT, "answer", silent)
    out = asyncio.run(station.assistant_ask({"text": "Pourquoi ce score ?"}))
    assert out["held_reason"] == "assistant_silent"
    assert out["answer"].startswith(station.LATE), "a slow model is not a stopped one"


def test_an_empty_or_endless_question_is_refused():
    for body in ({"text": ""}, {"text": "x" * 301}, {}):
        with pytest.raises(HTTPException) as bad:
            asyncio.run(station.assistant_ask(body))
        assert bad.value.status_code == 400
    with pytest.raises(HTTPException) as unknown:
        asyncio.run(station.assistant_ask({"text": "Pourquoi ?", "patient_id": "P-999"}))
    assert unknown.value.status_code == 404


def test_a_question_and_its_answer_carry_the_language_asked_for(monkeypatch):
    monkeypatch.setattr(station.CLIENT, "available", True)
    seen = {}

    async def echo(question, facts):
        seen["facts"] = facts
        return {"answer": "Your score comes from the breathing rate.", "grounded_in": "measurements"}

    monkeypatch.setattr(station.CLIENT, "answer", echo)
    out = asyncio.run(station.assistant_ask({"text": "Why this score?", "lang": "en", "self": True}))
    assert out["lang"] == "en" and out["spoken"] == out["answer"]
    assert "Answer in English" in seen["facts"] and seen["facts"].startswith(station.ANSWER_HEAD_SELF)


def test_the_manifest_tells_the_operator_both_new_things():
    from server.ai.capabilities import CAPABILITIES

    ids = {c["id"]: c for c in CAPABILITIES}
    assert ids["ask"]["needs_ai"] is True and "format fermé" in ids["ask"]["does"]
    assert ids["speak"]["needs_ai"] is False and "Piper" in ids["speak"]["does"]
