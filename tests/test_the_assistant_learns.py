"""MedBox learns from every request, and generalises within its own actions.

A phrase the allow-list does not know goes to the phrase book, then to the
model, which may only choose among the station's own actions under a grammar.
What the model decides once is written down, so the same words next time are
resolved with no model at all; an operator's correction outranks the model;
and every request is journaled with how it was understood.

None of this can add an action, touch a measurement, or reinterpret an
explicit declaration.
"""
from __future__ import annotations

import asyncio
import sqlite3
import sys
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server import app as station  # noqa: E402
from server.ai import intent as intent_module  # noqa: E402
from server.commands import classify  # noqa: E402
from server.learning import INTENTS, Learning, candidates, normalize  # noqa: E402


@pytest.fixture
def book():
    return Learning(sqlite3.connect(":memory:"))


def test_the_same_words_in_any_spelling_are_one_phrase():
    assert normalize("MedBox, montre-moi le PLUS malade !") == "montre moi le plus malade"
    assert normalize("  Med Box  montre-moi le plus malade") == "montre moi le plus malade"
    assert normalize("Montre-moi le plus malade") == "montre moi le plus malade"


def test_what_was_learned_once_is_deterministic_after(book):
    assert book.lookup("montre-moi le plus malade") is None
    assert book.learn("MedBox, montre-moi le plus malade", "worst", "model")
    assert book.lookup("montre moi le plus malade") == "worst"
    assert book.phrases()[0]["uses"] == 1


def test_an_operator_outranks_the_model_and_the_book_cannot_invent_actions(book):
    book.learn("passe au suivant s'il te plaît", "worst", "model")
    book.learn("passe au suivant s'il te plaît", "next", "operator")
    assert book.lookup("passe au suivant s il te plait") == "next"
    assert book.learn("passe au suivant s'il te plaît", "worst", "model") is False
    assert book.learn("passe au suivant s'il te plaît", "worst", "lexicon") is False
    with pytest.raises(ValueError):
        book.learn("éteins le réacteur", "shutdown_reactor", "operator")


def test_every_request_is_journaled(book):
    book.record("MedBox aide", "help", "allowlist", None)
    book.record("montre le pire", "worst", "model", "P-01")
    assert book.stats() == {"requests": 2, "by": {"allowlist": 1, "model": 1}, "learned_phrases": 0}
    assert book.recent(1)[0]["text"] == "montre le pire"


def test_an_unknown_phrase_is_not_an_explicit_declaration():
    assert classify("déclare : j'ai mal à la tête").explicit is True
    assert classify("montre-moi le plus malade").explicit is False
    assert classify("prioritaire").explicit is True


def _model_answering(payload: str):
    """A transport standing in for Ollama, answering /api/chat with `payload`."""
    def handler(request):
        if request.url.path == "/api/chat":
            return httpx.Response(200, json={"message": {"content": payload}})
        return httpx.Response(200, json={"version": "0.13.1", "models": []})
    return httpx.MockTransport(handler)


@pytest.fixture
def model(monkeypatch):
    real = httpx.AsyncClient
    monkeypatch.setattr(intent_module.CLIENT, "available", True)
    monkeypatch.setattr(intent_module.CLIENT, "stand_in", False)

    def install(payload: str):
        monkeypatch.setattr(intent_module.httpx, "AsyncClient",
                            lambda **kw: real(transport=_model_answering(payload)))
    return install


def test_the_model_may_only_pick_one_of_the_stations_own_actions(model):
    model('{"intent": "worst"}')
    assert asyncio.run(intent_module.classify("montre-moi le plus malade", False)) == "worst"
    model('{"intent": "open_airlock"}')
    assert asyncio.run(intent_module.classify("ouvre le sas", False)) is None
    model('this is not json')
    assert asyncio.run(intent_module.classify("n'importe quoi", False)) is None


def test_a_dead_model_files_the_words_as_before(monkeypatch):
    monkeypatch.setattr(intent_module.CLIENT, "available", False)
    assert asyncio.run(intent_module.classify("montre-moi le plus malade", False)) is None


def _counting(monkeypatch):
    calls = []
    real_classify = intent_module.classify

    async def counting(text, has_selection, allowed=None):
        calls.append((text, list(allowed or [])))
        return await real_classify(text, has_selection, allowed)

    monkeypatch.setattr(station, "classify_intent", counting)
    return calls


def test_one_plausible_reading_needs_no_model_and_is_learned(model, monkeypatch):
    """« montre-moi le plus malade » has one plausible intent (malade -> worst):
    resolved by the lexicon, instantly, and written to the book."""
    station.STATION._frame()
    station.STATION.learning = Learning(sqlite3.connect(":memory:"))
    model('{"intent": "next"}')  # the model would have said next; it is not asked
    calls = _counting(monkeypatch)
    first = asyncio.run(station.assistant_command({"text": "MedBox, montre-moi le plus malade"}))
    assert first["action"] == "select" and first["resolved_by"] == "lexicon" and first["learned"] is True
    second = asyncio.run(station.assistant_command({"text": "montre moi le plus malade"}))
    assert second["resolved_by"] == "learned"
    assert calls == [], "the model was consulted for a phrase with one plausible reading"
    assert station.STATION.learning.stats()["requests"] == 2


def test_nothing_the_station_does_is_none_without_asking_the_model(model, monkeypatch):
    """« ouvre le sas et éteins le réacteur » became a medical call, learned
    for good, when the model saw the whole menu. No lexicon word: no model."""
    station.STATION._frame()
    station.STATION.learning = Learning(sqlite3.connect(":memory:"))
    model('{"intent": "doctor_call"}')
    calls = _counting(monkeypatch)
    out = asyncio.run(station.assistant_command({"text": "MedBox, ouvre le sas et éteins le réacteur"}))
    assert out["resolved_by"] == "none" and out["action"] == "none"
    assert calls == [] and station.STATION.learning.stats()["learned_phrases"] == 0


def test_the_model_arbitrates_only_between_plausible_readings(model, monkeypatch):
    """« passe au suivant, le plus malade » is plausibly next or worst; the
    model chooses between those two and nothing else."""
    station.STATION._frame()
    station.STATION.learning = Learning(sqlite3.connect(":memory:"))
    model('{"intent": "worst"}')
    calls = _counting(monkeypatch)
    out = asyncio.run(station.assistant_command({"text": "passe au suivant, le plus malade"}))
    assert out["resolved_by"] == "model" and out["action"] == "select"
    assert calls == [("passe au suivant, le plus malade", ["worst", "next"])]
    model('{"intent": "doctor_call"}')  # outside the shortlist: refused even if answered
    assert asyncio.run(intent_module.classify("x", False, ["worst", "next"])) is None


def test_an_explicit_declaration_is_never_reinterpreted(model):
    station.STATION._frame()
    station.STATION.learning = Learning(sqlite3.connect(":memory:"))
    model('{"intent": "worst"}')
    pid = station.STATION._board()[0]["patient"]["id"]
    out = asyncio.run(station.assistant_command({"text": "déclare : montre-moi le plus malade", "patient_id": pid}))
    assert out["action"] == "reported" and out["resolved_by"] == "allowlist"
    station.STATION.symptoms.clear()


def test_the_operator_can_teach_and_the_lesson_is_readable():
    station.STATION.learning = Learning(sqlite3.connect(":memory:"))
    out = asyncio.run(station.assistant_feedback({"text": "qui est le plus mal en point", "intent": "worst"}))
    assert out["learned"] is True
    learned = asyncio.run(station.assistant_learned())
    assert learned["phrases"][0]["source"] == "operator"
    assert set(learned["intents"]) == set(INTENTS)
    with pytest.raises(station.HTTPException):
        asyncio.run(station.assistant_feedback({"text": "x", "intent": "self_destruct"}))


def test_the_lexicon_shortlists_in_both_languages():
    assert candidates("MedBox, qui est le plus mal en point ?") == ["worst"]
    assert candidates("who is the sickest") == ["worst"]
    assert candidates("passe au suivant, le plus malade") == ["worst", "next"]
    assert candidates("ouvre le sas et éteins le réacteur") == []
    assert candidates("pourquoi ce score") == ["why"]
