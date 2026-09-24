"""The text mode never invents who is isolated.

Eddy's page, 24 Sep: « Qui est en isolement ? » with nobody isolated, and
the model answered that two members were. Since then the station writes
the crew's state into the facts, answers the isolation and crew questions
itself at once, and replaces any answer the model itself calls ungrounded.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server import app as station  # noqa: E402


def test_the_crew_facts_only_name_real_members():
    facts, screen, spoken = station._crew_facts()
    names = {str(e["patient"].get("name")) for e in station.STATION.latest.values()}
    assert f"{len(station.STATION.latest)} membres" in facts
    assert "Ne citez que ces noms" in facts
    for word in ("isolement", "surveiller"):
        assert word in facts.lower()
    # Every name the station shows is a member; nobody is invented.
    import re
    for segment in re.split(r"[;:,]", screen):
        token = segment.strip().rstrip(".").split(" (")[0]
        if not token or token.startswith(("Équipage de", "Tout l’équipage", "en isolement", "isolement décidé", "à surveiller")):
            continue
        assert token in names, token
    assert not any(ch.isdigit() for ch in spoken.replace("zone", ""))  # the voice says names, not counts


def test_isolation_and_crew_questions_are_answered_by_the_station_at_once():
    for q in ("Qui est en isolement ?", "Y a-t-il quelqu’un en quarantaine ?", "Comment va l’équipage ?",
              "Combien de personnes à bord sont malades ?"):
        out = station._station_shortcut(q, None)
        assert out is not None, q
        assert out["grounded_in"] == "manual" and out["held_reason"] is None and out["resolved_by"] == "station"
        assert out["answer"] and out["spoken"]
        assert "L’assistant est arrêté" not in out["answer"]
    # A member's own question, or anything else, still goes to the model.
    assert station._station_shortcut("Qui est en isolement ?", "P-01") is None
    assert station._station_shortcut("Pourquoi mon pouls monte ?", None) is None


def test_the_fallback_sentences_name_the_real_reason():
    assert station.DOWN.startswith("Le référent est arrêté")
    assert station.LATE.startswith("Le référent n’a pas répondu à temps")
    assert station.UNGROUNDED.startswith("Le référent n’a rien trouvé")
    facts, screen, spoken = station._facts_for(None)
    assert not screen.startswith("L’assistant est arrêté"), "the reason is added by the route, not the facts"
    assert station._without_down_prefix("L’assistant est arrêté ; voici sa dernière évaluation.") == "voici sa dernière évaluation."


def test_the_route_replaces_an_ungrounded_answer(monkeypatch):
    import asyncio

    class Client:
        available = True
        stand_in = False
        last_error = None

        async def answer(self, text, facts):
            return {"answer": "Les deux membres sont en isolement.", "grounded_in": "nothing"}

    monkeypatch.setattr(station, "CLIENT", Client())
    out = asyncio.run(station.assistant_ask({"text": "Qui a de la fièvre ?", "lang": "fr"}))
    assert out["held_reason"] == "ungrounded"
    assert "Les deux membres" not in out["answer"]
    assert out["answer"].startswith(station.UNGROUNDED)
    assert out["grounded_in"] == "manual"
