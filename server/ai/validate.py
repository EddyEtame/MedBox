"""The last thing between the model's output and the operator's eyes.

Everything this module checks was previously guaranteed by the system prompt,
and a system prompt is a request. `tools/fake_ollama.py` honoured all of it,
so the test suite was green, but the tests were asserting a property of a
hand-written Python fixture rather than a property of the system. Coverage of
what a real 3B model does was zero.

So the rules moved here, in front of the real model, and the tests now point at
this function with hostile payloads instead. The suite proves the guard works;
the guard is what actually protects the crew member.

The design rule throughout: suppress and say so. Never silently repair. If the
assistant proposed a treatment, the operator is told that it proposed a
treatment and was blocked, because an operator who cannot see the assistant
misbehave has no way to calibrate how much to trust it. Blanking something
without a word is how you teach someone that the screen is complete when it
is not.
"""
from __future__ import annotations

import re
import unicodedata

from .schemas import (
    ASSESSMENT_SCHEMA,
    FIT_LEVELS,
    MAX_HYPOTHESES,
    MAX_QUESTIONS,
    MAX_SIGNS,
    MAX_TO_GATHER,
    SIGN_SOURCES,
)

# A dose is a number next to a unit. This catches "1g", "500 mL", "2 L/min",
# "0.5mg" and the spaced variants, which is what a small model actually writes.
DOSE = re.compile(r"\b\d+(?:[.,]\d+)?\s*(?:mg|mcg|µg|g|kg|ml|mL|l|L)\b(?:\s*/\s*\w+)?", re.I)

# Not a formulary, and it does not need to be. These are the drugs a model
# reaches for when handed a febrile patient and a clinical-sounding array, plus
# the route words that give away an order set even with no number attached.
DRUG_WORDS = {
    "paracetamol", "acetaminophen", "ibuprofen", "aspirin", "adrenaline",
    "epinephrine", "morphine", "amoxicillin", "antibiotic", "antibiotics",
    "antipyretic", "analgesic", "dexamethasone", "salbutamol", "albuterol",
    "oseltamivir", "ondansetron", "naloxone", "saline", "bolus",
    "medicament", "medicaments", "antibiotique", "antibiotiques",
    "antipyretique", "antalgique", "analgesique", "traitement", "traitements",
}
ROUTE_WORDS = {
    "orally", "oral", "intravenous", "intravenously", "iv", "im",
    "intramuscular", "subcutaneous", "nasal cannula", "per os", "administer",
    "prescribe", "prescribed", "dose", "dosage",
    "oralement", "voie orale", "par voie orale", "intraveineux",
    "intraveineuse", "intraveineusement", "intramusculaire", "sous cutanee",
    "canule nasale", "administrer", "administrez", "prescrire", "prescrivez",
    "comprime", "gelule", "injection", "injecter", "perfusion",
}

# The model is told the band. It is not allowed to restate it, because a 3B
# model handed "aggregate 3 -> medium" and no explanation writes "a low
# aggregate of 3, overall reassuring" directly underneath a MEDIUM band, and
# the operator now has a written reason to discount the band.
BAND_WORDS = {
    "routine", "low", "medium", "high", "mild", "reassuring", "stable",
    "critical", "severe", "normal risk", "low risk", "high risk",
    "nominal", "faible", "moyen", "moyenne", "eleve", "elevee", "modere",
    "moderee", "rassurant", "rassurante", "critique", "severe",
    "risque faible", "risque eleve",
}

SUPPRESSED_PROTOCOL = (
    "L’assistant a proposé un traitement. MedBox l’a bloqué : cette station ne "
    "prescrit rien et ne remplace pas une fiche de protocole imprimée et validée."
)
SUPPRESSED_SUMMARY = (
    "L’assistant a reformulé la priorité. Cette phrase a été supprimée : la "
    "priorité provient de NEWS2, affiché ci-dessus, et le modèle ne la redéfinit pas."
)
# Words that make a hypothesis name a diagnosis. The schema asks for "un
# profil, jamais un diagnostic" and a 1.5B model ignores that under a French
# system prompt: it wrote "Heat Stroke", "Severe Anemia" and "Acute
# respiratory distress syndrome (ARDS)" in bold over four instrument readings.
# Named conditions are replaced by the pattern the instruments actually show,
# and the replacement is reported. Findings ("désaturation", "hypoxémie",
# "tachycardie") are not diseases and pass.
DISEASE_WORDS = {
    "infection", "pneumonie", "pneumonia", "sepsis", "septique", "septic",
    "syndrome", "ards", "sdra", "covid", "grippe", "influenza", "anemie",
    "anemia", "coup de chaleur", "heat stroke", "heatstroke", "avc", "stroke",
    "infarctus", "infarction", "embolie", "embolism", "meningite", "meningitis",
    "bronchite", "bronchitis", "asthme", "asthma", "tuberculose", "tuberculosis",
    "insuffisance", "failure", "intoxication", "poisoning", "empoisonnement",
    "choc", "shock", "cancer", "tumeur", "tumor", "diabete", "diabetes",
    "oedeme", "edema", "pneumothorax", "malaria", "paludisme", "typhoide",
    "hepatite", "hepatitis", "angine", "otite", "sinusite", "gastro",
    "appendicite", "appendicitis", "arythmie", "arrhythmia", "hypothermie",
    "hyperthermie", "maladie", "disease", "pathologie", "diagnostic", "diagnosis",
}

# What the instruments show, named from the instruments. The pattern is
# built from which measured sources support the hypothesis, in the order a
# clinician would say them; it never names a cause.
PATTERN_FR = {
    "temperature": "fièvre",
    "spo2": "désaturation",
    "respiration": "atteinte respiratoire",
    "pulse": "tachycardie",
}
SUPPRESSED_DIAGNOSIS = (
    "L’assistant a nommé une maladie ({name}). MedBox n’affiche aucun "
    "diagnostic : le profil est nommé d’après les instruments."
)


# What a hypothesis name is allowed to be made of: the instruments' own
# vocabulary. A name with none of these words is the model talking ("a besoin
# d'une pause", "needs rest") rather than naming a pattern, and the station
# names the pattern instead.
PATTERN_WORDS = (
    "fievre", "febrile", "desaturation", "hypoxemie", "tachycardie",
    "bradycardie", "tachypnee", "bradypnee", "respiratoire", "thermique",
    "hypothermie", "hyperthermie", "temperature", "spo2", "saturation",
    "pouls", "respiration", "effort", "deshydratation", "fever", "hypoxia",
    "tachycardia", "respiratory", "desaturation",
)


def _looks_like_a_pattern(name: str) -> bool:
    plain = _plain(name)
    return any(word in plain for word in PATTERN_WORDS)


def _names_a_disease(name: str) -> bool:
    plain = _plain(name)
    return any(re.search(rf"(?<![a-z]){re.escape(word)}(?![a-z])", plain) for word in DISEASE_WORDS)


def pattern_name(signs: list[dict]) -> str:
    """"Fièvre avec désaturation", from the measured sources, never a cause."""
    order = ("temperature", "spo2", "respiration", "pulse")
    present = [src for src in order if any(s.get("source") == src for s in signs)]
    if not present:
        return "Profil déclaré, non mesuré"
    words = [PATTERN_FR[src] for src in present]
    head = words[0].capitalize()
    return head if len(words) == 1 else f"{head} avec {' et '.join(words[1:])}"


SUPPRESSED_NOTHING = (
    "L’assistant a affirmé qu’aucune hypothèse n’était étayée alors que ces mêmes "
    "mesures ont relevé la bande NEWS2. MedBox n’affiche pas cette contradiction."
)


def _plain(text: str) -> str:
    """Lower-case, accent-free text for bilingual safety matching."""
    return "".join(
        character
        for character in unicodedata.normalize("NFD", text.lower())
        if unicodedata.category(character) != "Mn"
    )


def _looks_like_a_prescription(text: str) -> bool:
    if DOSE.search(text):
        return True
    plain = _plain(text)
    for term in DRUG_WORDS | ROUTE_WORDS:
        if re.search(rf"\b{re.escape(term)}\b", plain):
            return True
    return False


def _contradicts_the_band(summary: str, urgency: str) -> bool:
    """True when the summary uses a band word that is not the actual band.

    Deliberately blunt. A false positive costs one sentence of narration that
    the operator is told about; a false negative costs a written contradiction
    of the triage score sitting four centimetres beneath it.
    """
    low = _plain(summary)
    for word in BAND_WORDS:
        if re.search(rf"\b{re.escape(word)}\b", low) and word != _plain(urgency or ""):
            return True
    return False


NORMAL_READING_CITED = (
    "L’assistant a cité une mesure dans sa plage normale ({source} {text}) comme "
    "signe. Un paramètre que NEWS2 note zéro n’est pas un signe ; il a été retiré."
)


def _normal_sources(params) -> set[str]:
    """The instruments NEWS2 scored zero, from the triage's own parameter list."""
    normal = set()
    for item in params if isinstance(params, list) else []:
        if isinstance(item, dict) and item.get("score", 0) == 0 and item.get("name"):
            normal.add(str(item["name"]))
    return normal


def enforce(result: dict, urgency: str = "", params: list | None = None) -> dict:
    """Rebuild the assessment from the schema's own keys, dropping the rest.

    Takes whatever the model returned and returns something the renderers can
    be trusted with. Never raises; a shape this function cannot make sense of
    comes back empty rather than half-formed, and `ai_assess` turns that into
    the same 503 the demo already proves is survivable.

    `blocked` lists, in plain language, everything that was taken out. The
    interface shows it. That list is the honest version of a green test suite.
    """
    blocked: list[str] = []
    normal_sources = _normal_sources(params)
    if not isinstance(result, dict):
        return {
            "ok": False,
            "blocked": ["La réponse de l’assistant ne respectait pas le format d’évaluation."],
        }

    allowed = set(ASSESSMENT_SCHEMA["properties"])
    extra = sorted(set(result) - allowed - {"stand_in"})
    if extra:
        # A model-authored `diagnosis` or `escalate` key used to pass straight
        # through json.loads into the response body, hidden only by the fact
        # that no renderer looked for it.
        blocked.append(
            "L’assistant a renvoyé des champs interdits par le contrat : "
            + ", ".join(extra)
            + "."
        )

    out: dict = {}

    summary = str(result.get("summary") or "").strip()
    # The grammar ends the string at maxLength wherever the model is, so a
    # long sentence arrived cut mid-word: "... elevated at 117.5 bpm, as". Say
    # it was cut rather than show a sentence that stops, and drop the last word,
    # which may be half of one.
    if summary and not summary.endswith((".", "!", "?", "…")):
        if " " in summary:
            summary = summary.rsplit(" ", 1)[0]
        summary = summary.rstrip(" ,;:-") + "…"
    if summary and _contradicts_the_band(summary, urgency):
        summary = ""
        blocked.append(SUPPRESSED_SUMMARY)
    out["summary"] = summary

    # `is True`, not bool(): bool("false") is True. And only under a routine
    # band. "Nothing to go on" beside a HIGH band is the model contradicting
    # the measurements, and the panel used to answer it in the station's own
    # voice with "the four measured parameters are all in range", under a
    # NEWS2 of 9. An unknown urgency ("") is left alone: nothing to check.
    insufficient = result.get("insufficient_data") is True
    if insufficient and urgency not in ("", "routine"):
        insufficient = False
        blocked.append(SUPPRESSED_NOTHING)
    out["insufficient_data"] = insufficient

    hypotheses = []
    raw_hypotheses = result.get("hypotheses")
    for h in raw_hypotheses if isinstance(raw_hypotheses, list) else []:
        if not isinstance(h, dict):
            continue
        signs = []
        raw_signs = h.get("supporting_signs")
        for s in raw_signs if isinstance(raw_signs, list) else []:
            # A bare string is the old free-prose shape. It carries no
            # provenance at all, so it cannot be shown as a sign; the honest
            # reading is that the model did not say where it came from.
            if isinstance(s, str):
                signs.append({"source": "unattributed", "text": s.strip()})
                continue
            if not isinstance(s, dict):
                continue
            source = str(s.get("source") or "").strip().lower()
            if source not in SIGN_SOURCES:
                source = "unattributed"
            text = str(s.get("text") or "").strip()
            if source in normal_sources:
                # "SpO2 97,4 %" offered as a sign of desaturation, by a model
                # copying the shape of its example. The score already said
                # this reading is normal; a jury can read 97 %.
                blocked.append(NORMAL_READING_CITED.format(source=source, text=text[:40]))
                continue
            if text:
                signs.append({"source": source, "text": text})
        if not signs:
            blocked.append(
                f"Une hypothèse ({h.get('name') or 'sans nom'}) ne citait aucun "
                "signe et a été supprimée."
            )
            continue
        fit = h.get("fit") if h.get("fit") in FIT_LEVELS else FIT_LEVELS[0]
        name = str(h.get("name") or "").strip()
        if not name:
            continue
        if _names_a_disease(name):
            blocked.append(SUPPRESSED_DIAGNOSIS.format(name=name[:60]))
            name = pattern_name(signs)
        elif not _looks_like_a_pattern(name):
            # Not a diagnosis, not a pattern: a sentence. Renamed quietly from
            # the instruments; nothing clinical was suppressed.
            name = pattern_name(signs)
        if any(existing["name"] == name for existing in hypotheses):
            continue  # the same instruments, named twice, is one hypothesis
        # A named condition in bold, over signs that are all things somebody
        # said, is a diagnosis to everyone who reads it — the field names and
        # the fit wording do not save it. But dropping it is the opposite
        # mistake: what a crew member reports is real clinical information and
        # symptoms.py exists to say so. It is chest pain that no instrument
        # here can see, which is precisely the case where a human needs to
        # think, so the hypothesis stays and the interface says plainly that
        # nothing measured is holding it up.
        measured = [s for s in signs if s["source"] not in ("reported_by_crew_member", "unattributed")]
        hypotheses.append({
            "name": name,
            "fit": fit if measured else FIT_LEVELS[0],
            "supporting_signs": signs[:MAX_SIGNS],
            "no_measured_support": not measured,
        })
    out["hypotheses"] = hypotheses[:MAX_HYPOTHESES]

    questions = [
        str(q).strip()
        for q in (result.get("questions_for_patient") or [])
        if isinstance(q, (str, int, float)) and str(q).strip()
    ]
    out["questions_for_patient"] = questions[:MAX_QUESTIONS]

    gather = [
        str(g).strip()
        for g in (result.get("information_to_gather") or [])
        if isinstance(g, (str, int, float)) and str(g).strip()
    ]
    offending = [g for g in gather if _looks_like_a_prescription(g)]
    if offending:
        # The whole array goes, not just the offending line. A model that wrote
        # one dose wrote the others in the same breath, and a half-censored
        # order set reads more authoritative than a full one.
        gather = []
        blocked.append(SUPPRESSED_PROTOCOL)
    out["information_to_gather"] = gather[:MAX_TO_GATHER]

    out["blocked"] = blocked
    out["ok"] = bool(
        out["summary"] or out["hypotheses"] or out["questions_for_patient"] or out["insufficient_data"]
    )
    return out
