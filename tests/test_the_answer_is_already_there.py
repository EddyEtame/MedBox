"""The assistant's answer is there before anybody clicks.

On the demo laptop one French assessment takes about twenty seconds. Waiting
that long in front of a jury, twice, is the demo. So the station assesses the
worst crew members on its own initiative as soon as they leave routine, one at
a time, and a click returns the held answer at once with its age, as long as
it was written against the NEWS2 total on screen. Asking again is one flag.
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server import app as station  # noqa: E402

ANSWER = {
    "summary": "Température 39,1 °C et SpO2 92 % relevées.",
    "insufficient_data": False,
    "hypotheses": [{"name": "Fièvre avec désaturation", "fit": "several measurements fit",
                    "supporting_signs": [{"source": "temperature", "text": "39,1 °C"}]}],
    "questions_for_patient": ["Depuis quand ?"],
    "information_to_gather": ["Répéter les constantes dans 15 minutes."],
}


def _armed(monkeypatch, calls):
    async def fake_assess(patient, triage, history_note="", timeout=None):
        calls.append(patient["id"])
        return dict(ANSWER)

    monkeypatch.setattr(station.CLIENT, "assess", fake_assess)
    monkeypatch.setattr(station.CLIENT, "available", True)
    monkeypatch.setattr(station.CLIENT, "warming", False)
    station.STATION.assessments.clear()
    station.STATION._frame()
    pid = station.STATION._board()[0]["patient"]["id"]
    station.STATION.latest[pid]["triage"]["urgency"] = "high"
    station.STATION.latest[pid]["triage"]["total"] = 8
    station.STATION._note_prefetch_targets(station.STATION._board())
    return pid


def test_the_worst_crew_member_is_assessed_before_anybody_asks(monkeypatch):
    calls = []
    pid = _armed(monkeypatch, calls)
    assert pid in station.STATION._prefetch_wanted
    assert asyncio.run(station.STATION.prefetch_once()) == pid
    held = station.STATION.assessments[pid]
    assert held["ok"] and held["news2_at_assessment"] == 8 and calls == [pid]


def test_a_click_returns_the_held_answer_at_once(monkeypatch):
    calls = []
    pid = _armed(monkeypatch, calls)
    asyncio.run(station.STATION.prefetch_once())
    body = asyncio.run(station.ai_assess(pid)).body
    assert b'"cached":true' in body or b'"cached": true' in body
    assert calls == [pid], "the click asked the model again"


def test_a_held_answer_against_another_score_is_not_served(monkeypatch):
    calls = []
    pid = _armed(monkeypatch, calls)
    asyncio.run(station.STATION.prefetch_once())
    station.STATION.latest[pid]["triage"]["total"] = 9
    body = asyncio.run(station.ai_assess(pid)).body
    assert b'"cached":false' in body or b'"cached": false' in body
    assert calls == [pid, pid]


def test_fresh_asks_again_and_a_routine_crew_member_is_never_prefetched(monkeypatch):
    calls = []
    pid = _armed(monkeypatch, calls)
    asyncio.run(station.STATION.prefetch_once())
    asyncio.run(station.ai_assess(pid, fresh=True))
    assert calls == [pid, pid]
    routine = [r["patient"]["id"] for r in station.STATION._board() if r["triage"]["urgency"] == "routine"]
    assert routine and not (set(routine) & set(station.STATION._prefetch_wanted))


def test_a_dead_assistant_prefetches_nothing(monkeypatch):
    calls = []
    _armed(monkeypatch, calls)
    monkeypatch.setattr(station.CLIENT, "available", False)
    assert asyncio.run(station.STATION.prefetch_once()) is None
    assert calls == []
