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
    for word in ("isol", "surveiller"):
        assert word in facts.lower()
    # Every name the station shows is a member; nobody is invented.
    import re
    for segment in re.split(r"[;:,]", screen):
        token = segment.strip().rstrip(".").split(" (")[0]
        if not token or token.startswith(("Équipage de", "Tout l’équipage", "en isolement", "isolement décidé", "à surveiller", "personne en isolement")):
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


def test_the_introduction_is_the_stations_own_and_instant():
    """Eddy, 24 Sep: asked to present himself, the model found nothing. The
    introduction is station text, answered at once, for anyone."""
    for q in ("Présente-toi", "présentez-vous", "qui es-tu ?", "Who are you?", "c’est quoi MedBox ?"):
        out = station._station_shortcut(q, None)
        assert out is not None and out["resolved_by"] == "station", q
        assert "MedBox" in out["answer"] and out["spoken"].startswith("Je suis MedBox")
    assert station._station_shortcut("Présente-toi", "P-01") is not None
    # a vital question is the station's own too, since 24 Sep; an open one is the model's
    assert station._station_shortcut("Que penses-tu de la vie à bord ?", "P-01") is None


def test_the_text_mode_pays_for_a_short_prompt():
    """A typed question is answered from a slim sheet under a short system
    prompt, capped at 48 tokens and 8 seconds: three to five seconds is the
    target on the defence laptop."""
    from server.ai.schemas import ANSWER_SYSTEM, SYSTEM_PROMPT
    from server.config import CONFIG
    assert len(ANSWER_SYSTEM) < len(SYSTEM_PROMPT) / 3
    brief, _, _ = station._facts_for(None, brief=True)
    full, _, _ = station._facts_for(None)
    assert len(brief) < len(full) / 2 and "Ce que la station sait faire" not in brief
    assert CONFIG.ai.answer_timeout_seconds <= 10.0
    assert CONFIG.ai.keep_alive == "2h"
    src = (ROOT / "server" / "ai" / "ollama.py").read_text(encoding="utf-8")
    assert '"num_predict": 26' in src and '"content": SYSTEM_PROMPT' in src and "ANSWER_RULES_BRIEF" in src


def test_questions_go_to_the_small_model_and_assessments_keep_the_large_one():
    """Eddy, 24 Sep: three to five seconds. The 1.5B model generates 7 tokens
    a second on the defence laptop; questions go to a 0.5B model that is
    warmed and cached at start, assessments keep the 1.5B."""
    from server.config import CONFIG
    # Measured 24 Sep: the 0.5B model answered in 2 to 6 s with sentences a
    # jury must not hear. The setting exists; the 1.5B answers by default.
    assert CONFIG.ai.answer_model == ""
    src = (ROOT / "server" / "ai" / "ollama.py").read_text(encoding="utf-8")
    assert '"model": CONFIG.ai.answer_model or self.model' in src
    assert "second = dict(body, model=CONFIG.ai.answer_model" in src


def test_the_station_grounds_a_plain_answer_itself():
    """A plain-text answer is checked by the station: a crew name absent from
    the facts, or an isolation the registers do not hold, is not shown."""
    facts = "Équipage : 40 membres, 40 en routine ; à surveiller : personne ; isolés : personne ; isolement à confirmer : personne. Ne citez que ces noms."
    assert station._ungrounded("Merove est en isolement depuis ce matin.", facts)
    assert station._ungrounded("Deux membres sont en quarantaine.", facts)
    assert not station._ungrounded("Personne n’est en isolement ; tout l’équipage est dans sa plage habituelle.", facts)
    assert not station._ungrounded("Votre pouls est dans votre plage habituelle.", facts)


def test_a_members_state_and_vitals_are_answered_by_the_station(monkeypatch):
    """« Est-ce que je vais bien ? », « pourquoi mon pouls monte ? » : the
    registers hold the answer, in the second person, at once."""
    fake = {"patient": {"id": "P-99", "name": "Test", "temperature": 37.0, "spo2": 98.0, "pulse": 95.0, "respiration": 14.0, "systolic_bp": 120.0,
                        "baseline": {"temperature": 36.8, "spo2": 98.0, "pulse": 62.0, "respiration": 14.0, "systolic_bp": 120.0}},
            "triage": {"total": 1, "urgency": "low", "params": []}}
    station.STATION.latest["P-99"] = fake
    try:
        out = station._station_shortcut("Pourquoi mon pouls monte ?", "P-99", True)
        assert out and out["resolved_by"] == "station"
        assert out["answer"].startswith("Votre pouls est à 95") and "au-dessus" in out["answer"] and "priorité faible" in out["answer"]
        out = station._station_shortcut("Est-ce que je vais bien ?", "P-99", True)
        assert out and out["answer"].startswith("Vous êtes à surveiller") and "pouls plus rapide" in out["answer"]
        out = station._station_shortcut("Comment va-t-il ?", "P-99", False)
        assert out and out["answer"].startswith("Test est à surveiller")
        out = station._station_shortcut("Ma température ?", "P-99", True)
        assert out and "dans votre plage habituelle" in out["answer"]
        assert station._station_shortcut("Que penses-tu de la vie à bord ?", "P-99", True) is None
    finally:
        station.STATION.latest.pop("P-99", None)


def test_a_complaint_is_recorded_and_answered_by_the_station():
    """« J'ai mal à la tête, c'est grave ? » goes to the dossier as a quotation
    and is answered from the constants of the moment, at once."""
    fake = {"patient": {"id": "P-98", "name": "Essai", "temperature": 36.7, "spo2": 98.0, "pulse": 64.0, "respiration": 14.0, "systolic_bp": 121.0,
                        "baseline": {"temperature": 36.7, "spo2": 98.0, "pulse": 64.0, "respiration": 14.0, "systolic_bp": 121.0}},
            "triage": {"total": 0, "urgency": "routine", "params": []}}
    station.STATION.latest["P-98"] = fake
    try:
        out = station._station_shortcut("J'ai mal à la tête, c'est grave ?", "P-98", True)
        assert out and out["resolved_by"] == "station"
        assert out["answer"].startswith("Je note « J'ai mal à la tête, c'est grave") and "rien d’anormal" in out["answer"]
        assert any("mal à la tête" in r.get("text", "") for r in station.STATION.symptoms.for_patient("P-98"))
        out = station._station_shortcut("Comment va Essai ?", "P-98", False)
        assert out and out["answer"].startswith("Essai est en routine")
    finally:
        station.STATION.latest.pop("P-98", None)
        station.STATION.symptoms.clear("P-98")


def test_the_static_lines_sit_in_the_cached_prefix():
    """Rules, then facts, then the question: everything up to the first
    changed token is served from the prompt cache (35 tokens a second of
    prompt on the defence laptop, 24 Sep). And a question frees the model."""
    src = (ROOT / "server" / "ai" / "ollama.py").read_text(encoding="utf-8")
    assert 'f"{ANSWER_RULES_BRIEF}\\n{facts}\\n\\nQuestion : {question}\\n{ANSWER_CUE}"' in src
    app_src = (ROOT / "server" / "app.py").read_text(encoding="utf-8")
    assert "STATION.yield_to_question()" in app_src and "assess_or_join(patient_id)" in app_src
    assert "head = ANSWER_HEAD_SELF if second_person else ANSWER_HEAD_OPERATOR" in app_src
    assert 'f"{ANSWER_RULES_BRIEF}\\n{ANSWER_HEAD_SELF}\\n"' in src, "the warm-up primes the question prefix"


def test_a_member_named_in_the_question_is_its_subject():
    """« Comment va Brad ? » from Eddy's page is about Brad, in the third
    person; an ambiguous first name (three Alba on board) names nobody."""
    station.STATION._frame()
    assert station._named_member("Comment va Brad ?") == "P-02"
    assert station._named_member("Comment va Alba ?") is None
    assert station._named_member("Et le bradycarde ?") is None
    # What the ears write for a name half heard (25 Sep: « comment va
    # Anthony ? » came back as another first name): a known mishearing, a
    # close spelling, two short words for one name.
    assert station._named_member("comment va Antoine") == "P-04"
    assert station._named_member("MedBox. Comment va Rétonie ?") == "P-04"
    assert station._named_member("comment va me rover ?") == "P-06"
    assert station._named_member("comment va Frédérique ?") == "P-05"
    assert station._named_member("Comment va Brad ? Comment va Anthony ?") == "P-04", "the last « comment va » is the one said"
    out = station._station_shortcut("comment va Zorglub ?", None, False)
    assert out and out["answer"].startswith("Je n’ai pas reconnu ce nom") and "Brad" in out["answer"]
    out = station._station_shortcut("Comment va Brad ?", "P-01", True)
    assert out and out["answer"].startswith("Brad est")
    assert station._subject("Est-ce que je vais bien ?", "P-01", True) == ("P-01", True)


def test_a_question_carries_the_essentials_only():
    """The member's line: state, isolation, the vitals out of range with
    their numbers, what was declared. No crew list, no in-range numbers."""
    fake = {"patient": {"id": "P-97", "name": "Essai", "temperature": 38.4, "spo2": 98.0, "pulse": 64.0, "respiration": 14.0, "systolic_bp": 121.0,
                        "baseline": {"temperature": 36.7, "spo2": 98.0, "pulse": 64.0, "respiration": 14.0, "systolic_bp": 121.0}},
            "triage": {"total": 1, "urgency": "low", "params": [], "measured": [], "missing_news2": []}}
    station.STATION.latest["P-97"] = fake
    try:
        facts, screen, spoken = station._facts_for("P-97", brief=True)
        assert facts.startswith("Essai : NEWS2 1")
        assert "température 38.4 (base 36.7)" in facts and "le reste dans sa plage habituelle" in facts
        assert "pouls 64" not in facts and "Équipage" not in facts and "Déclaré" not in facts
        assert len(facts) < 200, facts
    finally:
        station.STATION.latest.pop("P-97", None)


def test_a_number_the_facts_do_not_hold_is_held_back():
    """« Pouls 112 /min » for a member whose facts carry no such number is
    not shown; a number the facts hold, in either decimal spelling, is."""
    facts = "Eddy : NEWS2 0 (routine), pas d’isolement proposé ; écarts : température 38.4 (base 36.7) ; le reste dans sa plage habituelle."
    assert station._ungrounded("Pouls 112 /min.", facts)
    assert not station._ungrounded("Votre température est à 38,4 contre 36.7 d’habitude ; score 0.", facts)
    assert not station._ungrounded("Reposez-vous et redemandez-moi dans une heure.", facts)


def test_the_models_json_habit_is_salvaged():
    """One time in three the small model answered in its assessment JSON,
    cut at the cap. The sentence inside is kept; an empty shell is nothing."""
    from server.ai.ollama import salvage_answer
    assert salvage_answer('{"answer": "Oui, tout est habituel.", "grounded_in": "manual"}')["answer"] == "Oui, tout est habituel."
    assert salvage_answer('{"summary": "Pas de changement nécessaire.", "insufficient_data": false}')["answer"] == "Pas de changement nécessaire."
    cut = salvage_answer('{"summary": "Température 37,8 °C, SpO2 93,8 %, pou')
    assert cut["answer"] == "Température 37,8 °C, SpO2 93,8 %, pou." and cut["grounded_in"] == "manual"
    assert salvage_answer('{"hypotheses": [')["grounded_in"] == "nothing"
    assert salvage_answer("“Oui, vos constantes sont habituelles.”")["answer"] == "Oui, vos constantes sont habituelles."
    src = (ROOT / "server" / "ai" / "ollama.py").read_text(encoding="utf-8")
    assert "Question : {question}\\n{ANSWER_CUE}" in src, "the cue is the last thing the model reads"


def test_activity_rest_and_what_to_do_are_answered_by_the_station():
    """« Est-ce que je peux faire du sport ? », « dois-je dormir plus ? »,
    « que dois-je faire ? » : from the state, at once; « oui » in routine."""
    fake = {"patient": {"id": "P-96", "name": "Essai", "temperature": 36.7, "spo2": 98.0, "pulse": 64.0, "respiration": 14.0, "systolic_bp": 121.0,
                        "baseline": {"temperature": 36.7, "spo2": 98.0, "pulse": 64.0, "respiration": 14.0, "systolic_bp": 121.0}},
            "triage": {"total": 0, "urgency": "routine", "params": []}}
    station.STATION.latest["P-96"] = fake
    try:
        out = station._station_shortcut("Est-ce que je peux faire du sport aujourd'hui ?", "P-96", True)
        assert out and out["resolved_by"] == "station" and out["answer"].startswith("Oui : score 0")
        out = station._station_shortcut("Est-ce que je dois dormir plus ?", "P-96", True)
        assert out and out["answer"].startswith("Rien ne l’impose")
        out = station._station_shortcut("Que dois-je faire maintenant ?", "P-96", True)
        assert out and out["answer"].startswith("Rien de particulier")
        fake["patient"]["temperature"] = 38.6
        fake["triage"].update({"total": 3, "urgency": "low"})
        out = station._station_shortcut("Je peux aller courir ?", "P-96", True)
        assert out and out["answer"].startswith("Pas aujourd’hui : score 3") and "fièvre" in out["answer"]
        out = station._station_shortcut("Est-ce qu’Essai peut travailler ?", "P-01", True)
        assert out and out["answer"].startswith("Pas aujourd’hui") and "Qu’il se repose" in out["answer"]
        assert station._station_shortcut("Que penses-tu de la vie à bord ?", "P-96", True) is None
    finally:
        station.STATION.latest.pop("P-96", None)
