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

from .schemas import ASSESSMENT_SCHEMA, FIT_LEVELS, SIGN_SOURCES

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
}
ROUTE_WORDS = {
    "orally", "oral", "intravenous", "intravenously", "iv", "im",
    "intramuscular", "subcutaneous", "nasal cannula", "per os", "administer",
    "prescribe", "prescribed", "dose", "dosage",
}

# The model is told the band. It is not allowed to restate it, because a 3B
# model handed "aggregate 3 -> medium" and no explanation writes "a low
# aggregate of 3, overall reassuring" directly underneath a MEDIUM band, and
# the operator now has a written reason to discount the band.
BAND_WORDS = {
    "routine", "low", "medium", "high", "mild", "reassuring", "stable",
    "critical", "severe", "normal risk", "low risk", "high risk",
}

SUPPRESSED_PROTOCOL = (
    "The assistant proposed a treatment. It was blocked: this station does not "
    "prescribe, and nothing here is a substitute for the printed protocol card."
)
SUPPRESSED_SUMMARY = (
    "The assistant restated the urgency in its own words. It was suppressed: "
    "urgency is NEWS2, shown above, and the assistant does not get a second vote."
)


def _looks_like_a_prescription(text: str) -> bool:
    if DOSE.search(text):
        return True
    words = set(re.findall(r"[a-z]+", text.lower()))
    if words & DRUG_WORDS:
        return True
    return bool(words & ROUTE_WORDS)


def _contradicts_the_band(summary: str, urgency: str) -> bool:
    """True when the summary uses a band word that is not the actual band.

    Deliberately blunt. A false positive costs one sentence of narration that
    the operator is told about; a false negative costs a written contradiction
    of the triage score sitting four centimetres beneath it.
    """
    low = summary.lower()
    for word in BAND_WORDS:
        if re.search(rf"\b{re.escape(word)}\b", low) and word != (urgency or "").lower():
            return True
    return False


def enforce(result: dict, urgency: str = "") -> dict:
    """Rebuild the assessment from the schema's own keys, dropping the rest.

    Takes whatever the model returned and returns something the renderers can
    be trusted with. Never raises; a shape this function cannot make sense of
    comes back empty rather than half-formed, and `ai_assess` turns that into
    the same 503 the demo already proves is survivable.

    `blocked` lists, in plain language, everything that was taken out. The
    interface shows it. That list is the honest version of a green test suite.
    """
    blocked: list[str] = []
    if not isinstance(result, dict):
        return {"ok": False, "blocked": ["The assistant returned something that was not an assessment."]}

    allowed = set(ASSESSMENT_SCHEMA["properties"])
    extra = sorted(set(result) - allowed - {"stand_in"})
    if extra:
        # A model-authored `diagnosis` or `escalate` key used to pass straight
        # through json.loads into the response body, hidden only by the fact
        # that no renderer looked for it.
        blocked.append(
            "The assistant returned fields it is not allowed to: " + ", ".join(extra) + "."
        )

    out: dict = {}

    summary = str(result.get("summary") or "").strip()
    if summary and _contradicts_the_band(summary, urgency):
        summary = ""
        blocked.append(SUPPRESSED_SUMMARY)
    out["summary"] = summary

    out["insufficient_data"] = bool(result.get("insufficient_data"))

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
            if text:
                signs.append({"source": source, "text": text})
        if not signs:
            blocked.append(
                f"A hypothesis ({h.get('name') or 'unnamed'}) cited no sign at all and was dropped."
            )
            continue
        fit = h.get("fit") if h.get("fit") in FIT_LEVELS else FIT_LEVELS[0]
        name = str(h.get("name") or "").strip()
        if not name:
            continue
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
            "supporting_signs": signs[:4],
            "no_measured_support": not measured,
        })
    out["hypotheses"] = hypotheses[:4]

    questions = [
        str(q).strip()
        for q in (result.get("questions_for_patient") or [])
        if isinstance(q, (str, int, float)) and str(q).strip()
    ]
    out["questions_for_patient"] = questions[:4]

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
    out["information_to_gather"] = gather[:3]

    out["blocked"] = blocked
    out["ok"] = bool(
        out["summary"] or out["hypotheses"] or out["questions_for_patient"] or out["insufficient_data"]
    )
    return out
