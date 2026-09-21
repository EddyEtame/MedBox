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
