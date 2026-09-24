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
    # A routine member without a page of their own is never prefetched; the
    # six with a page are queued after the worst, so that « Mon évaluation »
    # on stage is instant, and their routine assessment stands fifteen minutes.
    routine = [r["patient"]["id"] for r in station.STATION._board()
               if r["triage"]["urgency"] == "routine" and not station._has_a_page(r["patient"]["id"])]
    assert routine and not (set(routine) & set(station.STATION._prefetch_wanted))
    with_page = [p for p in station.STATION._prefetch_wanted if station._has_a_page(p)]
    assert with_page, "the members with a page are prepared before anybody clicks"
    assert station.STATION._prefetch_wanted.index(pid) < station.STATION._prefetch_wanted.index(with_page[0]) or pid in with_page
    assert station.assessment_fresh_for({"urgency": "routine"}) == 900.0
    assert station.assessment_fresh_for({"urgency": "high"}) == 180.0


def test_a_dead_assistant_prefetches_nothing(monkeypatch):
    calls = []
    _armed(monkeypatch, calls)
    monkeypatch.setattr(station.CLIENT, "available", False)
    assert asyncio.run(station.STATION.prefetch_once()) is None
    assert calls == []


def test_the_kill_moment_serves_what_the_assistant_wrote_before_it_died(monkeypatch):
    """Kill Ollama on stage, click again: the held answer, dated and labelled,
    not a 503. The measurements and the priority go on without it."""
    calls = []
    pid = _armed(monkeypatch, calls)
    asyncio.run(station.STATION.prefetch_once())
    station.STATION.latest[pid]["triage"]["total"] = 9   # the score moved on
    monkeypatch.setattr(station.CLIENT, "available", False)
    response = asyncio.run(station.ai_assess(pid))
    assert response.status_code == 200
    body = response.body
    assert b'"held_reason":"assistant_down"' in body or b'"held_reason": "assistant_down"' in body
    assert calls == [pid], "a dead assistant was asked again"


def test_a_question_drops_the_background_assessment_but_not_its_own_member():
    """24 Sep: a spoken question waited behind a prefetch and ran out its
    seconds. The prefetch is a task of its own now; a question cancels it,
    the on-demand assessment of the same member joins it instead."""
    async def scenario():
        started, dropped = asyncio.Event(), asyncio.Event()

        async def slow():
            started.set()
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                dropped.set()
                raise

        s = station.STATION
        s._prefetch_task = asyncio.create_task(slow())
        s._prefetch_pid = "P-07"
        await started.wait()
        s.yield_to_question("P-07")
        await asyncio.sleep(0.02)
        assert not dropped.is_set(), "the member being asked about keeps its assessment"
        s.yield_to_question()
        await asyncio.sleep(0.05)
        assert dropped.is_set(), "a question frees the model at once"
        s._prefetch_task = None
        s._prefetch_pid = None

    asyncio.run(scenario())


def test_the_prefetch_survives_being_dropped(monkeypatch):
    """The prefetcher's own loop is not the task that is cancelled: it logs
    and carries on, so the member is assessed later."""
    async def scenario():
        s = station.STATION
        gate = asyncio.Event()

        async def never(*a, **k):
            gate.set()
            await asyncio.sleep(30)

        monkeypatch.setattr(s, "assess_now", never)
        monkeypatch.setattr(station.CLIENT, "available", True)
        monkeypatch.setattr(station.CLIENT, "warming", False)
        s._prefetch_wanted = ["P-03"]
        s.questions_pending = 0
        run = asyncio.create_task(s.prefetch_once())
        await gate.wait()
        s.yield_to_question()
        assert await run == "P-03"
        assert s._prefetch_task is None

    asyncio.run(scenario())
