"""What the assistant can do, what it refuses to do, and how to ask.

The owner wanted the AI to explain its own help rather than shipping a static
guide. That is the right instinct, and it has one trap in it: during the demo
the model is killed live on stage. If the explanation lived inside the model,
the thing explaining the system would vanish at the exact moment the system
is proving it does not need the model.

So the manifest below is data the station owns. When the assistant is up it
narrates this in its own words. When it is dead the station renders the same
facts plainly, and the guide is still there. The model is the voice, never
the source.

Every entry says whether it needs the AI at all. Most do not, which is the
honest shape of this product: the AI is a narrator over a system that works
without it.
"""
from __future__ import annotations

# --------------------------------------------------------------- what it does
CAPABILITIES = [
    {
        "id": "patient_record",
        "title": "Keep patient answers and show measurement history",
        "does": "Both views record answers, show four measurement charts and urgency changes, and list scenario events. Answers survive restart and reach the next assessment as untrusted reported text. Quarantine contacts are recorded locally.",
        "needs_ai": False,
        "how": "Select a patient. Answer an assistant question with Yes, No, Unsure or free text, then ask again. The record is below the assessment.",
    },
    {
        "id": "triage",
        "title": "Rank the whole crew by how ill they are",
        "does": (
            "Every crew member is scored with NEWS2, the Royal College of "
            "Physicians early warning score, from the four vitals the hardware "
            "measures. The board and the ship are both ordered by it."
        ),
        "needs_ai": False,
        "how": "It is always running. Nothing to ask.",
    },
    {
        "id": "explain_score",
        "title": "Show you why someone scored what they scored",
        "does": (
            "Select a crew member and each vital carries the reason it earned "
            "its points, plus the list of which parameters were actually "
            "measured rather than assumed."
        ),
        "needs_ai": False,
        "how": "Click a crew member, on either view.",
    },
    {
        "id": "quarantine",
        "title": "Assign isolation and seal the zone behind them",
        "does": (
            "A febrile crew member with falling oxygen or rising respiration is "
            "assigned a quarantine berth. A zone counts as sealed from the "
            "moment one person is inside it, stops taking new arrivals once it "
            "is at capacity, and anyone left over is reported as awaiting a bed "
            "rather than quietly dropped. Release uses a demonstration-only minimum of 120 seconds "
            "and two clear complete readings at least two seconds apart; missing readings never release anyone. "
            "This is not a validated clinical isolation protocol."
        ),
        "needs_ai": False,
        "how": "Automatic. Watch the bulkheads close on the ship view.",
    },
    {
        "id": "report",
        "title": "Record what a crew member tells you",
        "does": (
            "Type it, or say it into the microphone. It is stored as their own "
            "words and passed to the assistant as something to check. It never "
            "changes the NEWS2 score, because nothing measured it."
        ),
        "needs_ai": False,
        "how": "Select a crew member, then the box under 'in their own words'.",
    },
    {
        "id": "hypotheses",
        "title": "Offer ranked hypotheses for one crew member",
        "does": (
            "The assistant reads that person's measurements and anything they "
            "reported, and offers possible explanations, each sign labelled with "
            "the instrument that recorded it, or marked as something the crew "
            "member said and nothing measured. It does not diagnose, it cannot "
            "change the urgency, and when the four parameters support nothing it "
            "is allowed to say so rather than invent a pattern."
        ),
        "needs_ai": True,
        "how": "Select a crew member and press 'ask the assistant'.",
    },
    {
        "id": "questions",
        "title": "Suggest what to ask the patient next",
        "does": (
            "Because the box measures four things and a person can tell you a "
            "hundred, the most useful thing a model can do here is tell you "
            "what to ask."
        ),
        "needs_ai": True,
        "how": "Included in every assessment.",
    },
]

# ------------------------------------------------------ what it will not do
REFUSALS = [
    {
        "never": "Diagnose",
        "why": (
            "It offers hypotheses with the signs behind them. There is no "
            "diagnosis field anywhere in the schema it is allowed to answer in, "
            "so it cannot emit one even if asked."
        ),
    },
    {
        "never": "Prescribe anything",
        "why": (
            "It has no field to put a treatment in. The one array it can fill "
            "is for observations and measurements to take, and the station "
            "drops the whole array and says so if a drug, a dose or a route "
            "appears in it. There is no doctor aboard and this box is not one."
        ),
    },
    {
        "never": "Change how urgent someone is",
        "why": (
            "Urgency is NEWS2, computed in Python from measurements. The model "
            "is not in that path and never reads it back."
        ),
    },
    {
        "never": "Act on something nobody measured",
        "why": (
            "Reported symptoms reach it marked as unverified claims. It is "
            "required to name the measurement behind every claim it makes."
        ),
    },
    {
        "never": "Block a reading",
        "why": (
            "It runs on a slow track. If it hangs or dies, vitals, triage, "
            "quarantine and recording carry on untouched. Kill it and watch."
        ),
    },
    {
        "never": "Reach the network",
        "why": "The model runs locally. The vessel has no contact with Earth.",
    },
]

# ------------------------------------------------------------------ shortcuts
# Short phrases that do a real thing. Most work with the model dead, which is
# deliberate: an operator should not have to learn which of their tools stop
# working when the assistant does.
SHORTCUTS = [
    {
        "phrase": "worst",
        "does": "Select the crew member with the highest NEWS2 score.",
        "needs_ai": False,
    },
    {
        "phrase": "next",
        "does": "Move to the next crew member down the triage order.",
        "needs_ai": False,
    },
    {
        "phrase": "why",
        "does": "Show how the selected score was built, parameter by parameter.",
        "needs_ai": False,
    },
    {
        "phrase": "isolated",
        "does": "Show who is in quarantine and which zones are sealed.",
        "needs_ai": False,
    },
    {
        "phrase": "said <words>",
        "does": "Record what this crew member just told you, in their words.",
        "needs_ai": False,
    },
    {
        "phrase": "assess",
        "does": "Ask the assistant for hypotheses on the selected crew member.",
        "needs_ai": True,
    },
    {
        "phrase": "ask",
        "does": "List what to ask this patient next.",
        "needs_ai": True,
    },
    {
        "phrase": "help",
        "does": "Explain what this box can and cannot do. Works with the AI dead.",
        "needs_ai": False,
    },
]


def manifest(ai_available: bool = False, stand_in: bool = False) -> dict:
    """Everything the interface needs to explain itself, model or no model."""
    return {
        "capabilities": CAPABILITIES,
        "refusals": REFUSALS,
        "shortcuts": SHORTCUTS,
        "ai_available": ai_available,
        "stand_in": stand_in,
        "without_ai": [c["id"] for c in CAPABILITIES if not c["needs_ai"]],
        "needs_ai": [c["id"] for c in CAPABILITIES if c["needs_ai"]],
    }


def self_explanation_prompt() -> str:
    """Ask the model to introduce the station in its own words.

    It is handed the facts rather than asked to recall them, because a 3B
    model asked "what can you do?" will cheerfully invent capabilities, and an
    invented capability in a medical interface is the worst possible failure
    of this whole feature.
    """
    can = "\n".join(
        f"- {c['title']}: {c['does']} "
        f"({'needs you' if c['needs_ai'] else 'works without you'})"
        for c in CAPABILITIES
    )
    wont = "\n".join(f"- Never {r['never'].lower()}: {r['why']}" for r in REFUSALS)
    keys = ", ".join(s["phrase"] for s in SHORTCUTS)
    return (
        "A crew member has just asked what this box can do for them.\n\n"
        "These are the facts. Do not add to them, and do not claim any ability "
        "that is not listed here:\n\n"
        f"WHAT IT DOES:\n{can}\n\n"
        f"WHAT IT WILL NOT DO:\n{wont}\n\n"
        f"SHORTCUTS THEY CAN TYPE OR SAY: {keys}\n\n"
        "Introduce yourself and the station in four sentences at most. Be plain "
        "and calm. Say early that most of this works whether or not you are "
        "running, and that the urgency ranking is never yours. Do not use bullet "
        "points. Do not invent a capability."
    )
