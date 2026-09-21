"""The guide must not promise anything the product does not do.

A help screen that lists a command nobody implemented is worse than no help
screen: it teaches an operator something false, and they find out while
holding a patient. These tests tie the manifest to the code that has to
honour it.
"""
from __future__ import annotations

import re
import sys
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
from server.quarantine import Assignment, QuarantineRegistry  # noqa: E402
from server.triage import assess  # noqa: E402

SHIP_JS = (ROOT / "web" / "ship.js").read_text(encoding="utf-8")


def test_every_advertised_shortcut_is_implemented():
    """The console must handle every phrase the guide lists."""
    handled = set(re.findall(r'word === "([a-z]+)"', SHIP_JS))
    for shortcut in SHORTCUTS:
        # "said <words>" is advertised with its argument; the verb is "said".
        verb = shortcut["phrase"].split()[0]
        assert verb in handled, (
            f"the guide advertises {shortcut['phrase']!r} but web/ship.js "
            f"handles only {sorted(handled)}"
        )


def test_no_command_is_implemented_without_being_documented():
    """The reverse: a hidden command is a command nobody will ever find."""
    handled = set(re.findall(r'word === "([a-z]+)"', SHIP_JS))
    advertised = {s["phrase"].split()[0] for s in SHORTCUTS}
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
    text = " ".join(r["never"].lower() + " " + r["why"].lower() for r in REFUSALS)
    for promise in ("diagnos", "urgen", "news2", "network", "measured"):
        assert promise in text, f"the guide never addresses {promise!r}"


def test_the_self_explanation_hands_the_model_the_facts():
    """A 3B model asked "what can you do?" will invent capabilities, and an
    invented capability in a medical interface is the worst failure this
    feature has available to it."""
    prompt = self_explanation_prompt()
    assert "Do not invent a capability" in prompt
    for c in CAPABILITIES:
        assert c["title"] in prompt, f"{c['title']!r} was not given to the model"
    for s in SHORTCUTS:
        assert s["phrase"] in prompt


def test_the_guide_describes_sealing_the_way_the_bulkheads_do_it():
    """Two-way pin on one sentence.

    The guide used to say zones "seal when full". The registry seals a zone
    from the moment one person is inside it, which is both the safer design
    and the one the ship view draws. So the sentence was wrong, not the code.
    Both halves are asserted here: change the rule without the wording, or the
    wording without the rule, and this fails.
    """
    registry = QuarantineRegistry(("A",), capacity=4)
    registry.assignments["c1"] = Assignment("c1", "A", 0.0, "fever with desaturation")

    zone = registry.to_dict()["zones"]["A"]
    assert zone["occupied"] < registry.capacity
    assert zone["sealed"] is True, (
        "the registry no longer seals on the first occupant, so the wording in "
        "server/ai/capabilities.py has to follow it"
    )

    entry = next(c for c in CAPABILITIES if c["id"] == "quarantine")
    text = (entry["title"] + " " + entry["does"]).lower()
    for claim in ("seal when full", "seal a zone when it fills", "sealed when full"):
        assert claim not in text, f"the guide promises {claim!r}; the code does not"
    assert "at capacity" in text, (
        "the guide has to say what capacity does govern, or a reader assumes "
        "it governs sealing"
    )


def test_overflow_is_reported_rather_than_quietly_dropped():
    """The other half of the same sentence. A full ship is the interesting
    case and the one the contamination scenario reaches, so the number of
    people with nowhere to go has to be visible rather than inferred from a
    roster that is shorter than it should be."""
    registry = QuarantineRegistry(("A",), capacity=1)
    febrile = dict(temperature=39.2, spo2=91.0, pulse=104.0, respiration=24.0)
    triage = assess(**febrile)

    first = registry.evaluate("c1", febrile, triage)
    second = registry.evaluate("c2", febrile, triage)

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
