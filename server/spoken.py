"""What the station says out loud, written for the ear.

The screen shows numbers with units and one-decimal precision. A voice reading
those is what Eddy heard on 24 September ("heart rates, diagnostics"), and it
is wrong: nobody says "SpO2 92.2 %" to a colleague across a room. What is
said here carries no numbers (the screen has them), names the observed
pattern in plain words, says once that it is not a diagnosis, asks the one
question, and stops.

Deterministic, and downstream of the validator: the model never writes what
the voice says. Its rebuilt output is the input here, and the fallback when
the model is dead is the station's own short sentence, not the fact sheet
with every baseline that the panel shows.
"""
from __future__ import annotations

NOT_A_DIAGNOSIS = "Ce n’est pas un diagnostic ; la priorité vient du score, pas de moi."
STATION_ALONE = (
    "L’assistant est arrêté. Je mesure cinq constantes et deux observations ; "
    "le score et l’isolement continuent sans lui."
)


def _lower_first(text: str) -> str:
    return text[:1].lower() + text[1:] if text else text


def _join_fr(items: list[str]) -> str:
    items = [item for item in items if item]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " et " + items[-1]


def spoken_assessment(name: str | None, body: dict) -> str:
    """One breath about a crew member, from a validated assessment."""
    if not isinstance(body, dict) or not body.get("ok"):
        return ""
    who = (name or "").strip() or "ce membre"
    parts: list[str] = []
    if body.get("held_reason") == "assistant_down":
        parts.append("L’assistant est arrêté ; voici ce qu’il avait préparé.")
    patterns = [
        _lower_first(str(h.get("name") or "").strip())
        for h in (body.get("hypotheses") or [])
        if isinstance(h, dict)
    ]
    patterns = [p for p in patterns if p]
    if patterns:
        parts.append(f"Pour {who}, le profil observé est : {_join_fr(patterns)}.")
    elif body.get("insufficient_data"):
        parts.append(f"Pour {who}, rien de mesuré ne sort de l’ordinaire.")
    else:
        parts.append(f"Pour {who}, l’assistant n’a rien retenu de mesurable.")
    parts.append(NOT_A_DIAGNOSIS)
    questions = [str(q).strip() for q in (body.get("questions_for_patient") or []) if str(q).strip()]
    gather = [str(g).strip() for g in (body.get("information_to_gather") or []) if str(g).strip()]
    if questions:
        parts.append(f"Question à lui poser : {questions[0]}")
    elif gather:
        parts.append(f"À mesurer : {gather[0].rstrip('.')}.")
    return " ".join(parts)


def spoken_station_answer(
    name: str | None = None,
    total: int | None = None,
    urgency_fr: str | None = None,
    isolation: str | None = None,
) -> str:
    """The station answering a question itself, because the model is absent."""
    if not name:
        return STATION_ALONE
    return f"L’assistant est arrêté. {name} : score {total}, priorité {urgency_fr}, {isolation}."
