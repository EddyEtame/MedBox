"""What the station says out loud, written for the ear.

The screen shows numbers with units. A voice reading those is what Eddy heard
on 24 September ("heart rates, diagnostics"), and it is wrong: nobody says
"SpO2 92.2 %" across a room. What is said here carries no numbers, names the
condition in plain words, states the decision, asks the one question, and
stops. The voice is the ship's medical referent and speaks like one.

Deterministic, and downstream of the validator: the model never writes what
the voice says. Its rebuilt output is the input here.
"""
from __future__ import annotations

STATION_ALONE = (
    "L’assistant est arrêté. Je mesure cinq constantes et deux observations ; "
    "le score et l’isolement continuent sans lui."
)

# The instrument patterns the validator produces, said as a clinician says them.
CONDITIONS = {
    "fièvre": "de la fièvre",
    "désaturation": "un manque d’oxygène",
    "atteinte respiratoire": "une gêne respiratoire",
    "tachycardie": "un rythme cardiaque trop rapide",
    "hypotension": "une tension basse",
    "fièvre avec atteinte respiratoire": "un syndrome respiratoire fébrile",
    "fièvre avec désaturation": "de la fièvre avec un manque d’oxygène",
    "profil déclaré, non mesuré": "des symptômes déclarés, sans mesure anormale",
}


def _lower_first(text: str) -> str:
    return text[:1].lower() + text[1:] if text else text


def _join_fr(items: list[str]) -> str:
    items = [item for item in items if item]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " et " + items[-1]


def condition_phrase(pattern: str) -> str:
    """« Fièvre avec désaturation » → « de la fièvre avec un manque d’oxygène »."""
    key = _lower_first(str(pattern or "").strip())
    if key in CONDITIONS:
        return CONDITIONS[key]
    parts = [p.strip() for p in key.replace(" et ", " avec ").split(" avec ") if p.strip()]
    said = [CONDITIONS.get(p, p) for p in parts]
    return _join_fr(said) if said else key


def decision_phrase(isolation: dict | None, urgency: str | None, second_person: bool) -> str:
    you = "vous" if second_person else None
    if isolation:
        zone = isolation.get("zone")
        if isolation.get("confirmed") and zone:
            return (f"Je {you} place en isolement, zone {zone}. Restez dans vos quartiers."
                    if you else f"Isolement en zone {zone}, en cours.")
        if isolation.get("confirmed"):
            return "Isolement décidé ; une place se libère." if not you else "Je vous place en isolement dès qu’une place se libère."
        return ("Je décide votre isolement ; l’équipage en est informé." if you
                else "J’ai décidé son isolement ; l’équipage doit en accuser réception.")
    if urgency in ("high", "medium"):
        return "Je vous garde en surveillance rapprochée." if you else "Surveillance rapprochée."
    if urgency == "low":
        return "Je surveille l’évolution." if you else "À surveiller."
    return "Rien d’inquiétant pour le moment."


def spoken_assessment(
    name: str | None,
    body: dict,
    isolation: dict | None = None,
    urgency: str | None = None,
    second_person: bool = False,
) -> str:
    """One breath about a crew member, from a validated assessment."""
    if not isinstance(body, dict) or not body.get("ok"):
        return ""
    who = (name or "").strip() or "ce membre"
    parts: list[str] = []
    if body.get("held_reason") == "assistant_down":
        parts.append("L’assistant est arrêté ; voici sa dernière évaluation.")
    patterns = [
        condition_phrase(str(h.get("name") or ""))
        for h in (body.get("hypotheses") or [])
        if isinstance(h, dict) and str(h.get("name") or "").strip()
    ]
    if patterns:
        parts.append(f"{who}, vous présentez {_join_fr(patterns)}." if second_person
                     else f"{who} présente {_join_fr(patterns)}.")
    elif body.get("insufficient_data"):
        parts.append(f"{who}, vos mesures sont dans votre plage habituelle." if second_person
                     else f"{who} : rien de mesuré ne sort de l’ordinaire.")
    else:
        parts.append(f"{who}, je n’ai rien retenu de mesurable pour l’instant." if second_person
                     else f"{who} : rien de mesurable retenu pour l’instant.")
    parts.append(decision_phrase(isolation, urgency, second_person))
    questions = [str(q).strip() for q in (body.get("questions_for_patient") or []) if str(q).strip()]
    gather = [str(g).strip() for g in (body.get("information_to_gather") or []) if str(g).strip()]
    if questions:
        parts.append(questions[0] if second_person else f"Question à lui poser : {questions[0]}")
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


def _reason_conditions(reason: str) -> list[str]:
    """The isolation rule's reason, "fever 38.0 C with respiration 24/min", said plainly."""
    low = str(reason or "").lower()
    said = []
    if "fever" in low or "fièvre" in low or "temperature" in low:
        said.append("de la fièvre")
    if "spo2" in low or "desaturation" in low or "oxygen" in low or "saturation" in low:
        said.append("un manque d’oxygène")
    if "respiration" in low or "breath" in low:
        said.append("une respiration rapide")
    return said or ["des mesures hors de votre plage habituelle"]


def spoken_isolation_message(name: str, role: str, change: dict) -> tuple[str, str, str]:
    """(text for the panels, spoken to the crew, spoken to the person).

    The referent has decided an isolation. The crew dashboard gets it in the
    third person and must acknowledge; the person gets it in the second
    person, as an instruction, because that is what a ship's doctor does.
    """
    conditions = _join_fr(_reason_conditions(change.get("reason", "")))
    zone = change.get("zone")
    confirmed = bool(change.get("confirmed"))
    if confirmed and zone:
        where_text, where_crew, where_me = (f"Zone {zone} attribuée.", f"zone {zone}", f", zone {zone}")
    elif confirmed:
        where_text, where_crew, where_me = ("En attente d’une place.", "en attente d’une place", " dès qu’une place se libère")
    else:
        where_text, where_crew, where_me = ("Zone à attribuer.", "zone à attribuer", "")
    text = (f"Isolement décidé pour {name} ({role}) : {conditions}, exposition confirmée. "
            f"{where_text} Accusez réception.")
    crew = f"{name} présente {conditions}. J’ai décidé son isolement, {where_crew}. Accusez réception."
    me = (f"{name}, vous présentez {conditions}. Je vous place en isolement{where_me}. "
          "Restez dans vos quartiers ; je vous suis de près.")
    return text, crew, me


def spoken_personal_intro(name: str, week_ok: bool, urgency: str | None, isolation: dict | None) -> str:
    """What the referent says to a person when they open their own page."""
    week = ("Cette semaine, vos constantes sont restées dans votre plage habituelle."
            if week_ok else "Cette semaine, j’ai vu des écarts dans vos constantes.")
    if isolation and isolation.get("confirmed"):
        today = "Aujourd’hui, vous êtes en isolement ; je vous suis de près."
    elif isolation:
        today = "Aujourd’hui, j’ai décidé votre isolement ; restez dans vos quartiers."
    elif urgency in ("high", "medium"):
        today = "Aujourd’hui, je vois un écart et je vous surveille de près."
    elif urgency == "low":
        today = "Aujourd’hui, un léger écart ; rien d’inquiétant, je surveille."
    else:
        today = "Aujourd’hui, tout est nominal."
    return f"Bonjour {name}. Je suis MedBox, le référent médical du bord. {week} {today} Posez-moi vos questions."
