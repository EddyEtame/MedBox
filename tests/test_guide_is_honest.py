"""The guide must not promise anything the product does not do.

A help screen that lists a command nobody implemented is worse than no help
screen: it teaches an operator something false, and they find out while
holding a patient. These tests tie the manifest to the code that has to
honour it.
"""
from __future__ import annotations

import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server.ai.capabilities import (  # noqa: E402
    CAPABILITIES,
    REFUSALS,
    SHORTCUTS,
    manifest,
    self_explanation_prompt,
)
from server.quarantine import QuarantineRegistry  # noqa: E402
from server.triage import assess  # noqa: E402

SHIP_JS = (ROOT / "web" / "ship.js").read_text(encoding="utf-8")


def advertised_verbs() -> set[str]:
    """French commands and their backward-compatible English aliases."""
    phrases = []
    for shortcut in SHORTCUTS:
        phrases.append(shortcut["phrase"])
        phrases.extend(shortcut.get("aliases", []))
    return {
        "".join(
            character
            for character in unicodedata.normalize("NFD", phrase.split()[0].lower())
            if unicodedata.category(character) != "Mn" and character.isalpha()
        )
        for phrase in phrases
    }


def implemented_verbs() -> set[str]:
    """Recognise both equality chains and ``[...].includes(word)`` dispatch."""
    handled = set(re.findall(r'word\s*===\s*"([^"]+)"', SHIP_JS))
    for group in re.findall(r'\[([^\]]+)\]\.includes\(word\)', SHIP_JS):
        handled.update(re.findall(r'"([^"]+)"', group))
    return handled


def test_every_advertised_shortcut_is_implemented():
    """The console must handle every phrase the guide lists."""
    handled = implemented_verbs()
    for verb in advertised_verbs():
        assert verb in handled, (
            f"the guide advertises command {verb!r} but web/ship.js "
            f"handles only {sorted(handled)}"
        )


def test_no_command_is_implemented_without_being_documented():
    """The reverse: a hidden command is a command nobody will ever find."""
    handled = implemented_verbs()
    advertised = advertised_verbs()
    assert handled <= advertised, (
        f"web/ship.js handles {sorted(handled - advertised)}, which the guide "
        "never mentions"
    )


def test_most_of_the_product_survives_the_assistant_dying():
    """If killing the model broke most features, the architecture claim is a
    slogan rather than a design."""
    m = manifest()
    assert len(m["without_ai"]) > len(m["needs_ai"])


def test_the_guide_itself_does_not_need_the_assistant():
    """It is rendered from this data, which is why it survives the kill."""
    m = manifest(ai_available=False)
    assert m["capabilities"] and m["refusals"] and m["shortcuts"]


def test_shortcuts_that_need_the_assistant_are_flagged_as_such():
    for s in SHORTCUTS:
        assert isinstance(s["needs_ai"], bool)
    assert any(not s["needs_ai"] for s in SHORTCUTS), "everything cannot need the AI"


def test_the_refusals_cover_the_claims_the_project_makes():
    refusal_ids = {refusal["id"] for refusal in REFUSALS}
    required = {"diagnosis", "prescription", "urgency", "unmeasured", "network"}
    assert required <= refusal_ids, f"the guide never addresses {required - refusal_ids}"


def test_the_self_explanation_hands_the_model_the_facts():
    """The model may greet; station-owned text must carry every safety claim."""
    from server.ai.capabilities import deterministic_introduction

    prompt = self_explanation_prompt()
    assert "une seule salutation" in prompt
    assert "Aucun conseil médical" in prompt
    assert len(prompt) < 250

    intro = deterministic_introduction()
    for phrase in (
        "cinq constantes", "lignes de base", "vaisseau 3D", "référent médical",
        "décide des isolements", "accuse réception", "aucun médicament",
        "microphone", "audio n’est pas conservé", "écoute locale continue",
        "J’accepte", "oui", "I accept", "yes",
    ):
        assert phrase in intro


def test_the_guide_describes_human_confirmation_and_manual_release():
    """A candidate must not consume a berth or seal a zone before confirmation."""
    registry = QuarantineRegistry(
        ("A",), capacity=4, require_confirmation=True, allow_automatic_release=False
    )
    febrile = dict(temperature=39.2, spo2=91.0, pulse=104.0, respiration=24.0)
    candidate = registry.evaluate("c1", febrile, assess(**febrile))
    assert candidate is not None and candidate.confirmed is False
    assert registry.to_dict()["zones"]["A"] == {
        "occupied": 0,
        "capacity": 4,
        "sealed": False,
    }

    registry.confirm("c1")
    zone = registry.to_dict()["zones"]["A"]
    assert zone["occupied"] == 1
    assert zone["sealed"] is True

    # Clearing readings cannot silently release a confirmed person.
    nominal = dict(temperature=36.8, spo2=98.0, pulse=70.0, respiration=15.0)
    assert registry.evaluate("c1", nominal, assess(**nominal)) is None
    assert "c1" in registry.assignments

    entry = next(c for c in CAPABILITIES if c["id"] == "quarantine")
    text = (entry["title"] + " " + entry["does"]).lower()
    for required in ("confirmer", "capacité", "levée", "manuelle"):
        assert required in text, f"le guide de quarantaine omet {required!r}"
    assert "automatiquement" in text  # present only in the explicit negation
    assert "rien n’est isolé automatiquement" in text


def test_overflow_is_reported_rather_than_quietly_dropped():
    """The other half of the same sentence. A full ship is the interesting
    case and the one the contamination scenario reaches, so the number of
    people with nowhere to go has to be visible rather than inferred from a
    roster that is shorter than it should be."""
    registry = QuarantineRegistry(
        ("A",), capacity=1, require_confirmation=True, allow_automatic_release=False
    )
    febrile = dict(temperature=39.2, spo2=91.0, pulse=104.0, respiration=24.0)
    triage = assess(**febrile)

    registry.evaluate("c1", febrile, triage)
    first = registry.confirm("c1")
    registry.evaluate("c2", febrile, triage)
    second = registry.confirm("c2")

    assert first is not None and first.zone == "A"
    assert second is not None and second.zone is None
    assert second.to_dict()["awaiting_bed"] is True

    state = registry.to_dict()
    assert state["awaiting_bed"] == 1, "a crew member with no berth vanished"
    assert len(state["assignments"]) == 2, "both are still on the register"


def test_both_views_draw_the_crew_who_have_no_berth():
    """The guide says a crew member awaiting a bed is on the screen.

    For a while the server counted them and neither view drew them, so the
    only way to learn the ship had run out of isolation space was to type
    `isolated` on the 3D console -- which is to say, during an outbreak, not
    at all. Both views read the count now, and this is what keeps it that way.
    """
    board_js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    for name, source in (("web/app.js", board_js), ("web/ship.js", SHIP_JS)):
        assert "awaiting_bed" in source, (
            f"{name} never reads awaiting_bed, so the guide's claim that a "
            "crew member with no berth is drawn on this view is false"
        )
