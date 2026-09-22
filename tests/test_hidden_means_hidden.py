"""The rule that a hidden element is actually hidden.

`el.hidden = true` works through one rule in the browser's own stylesheet,
`[hidden] { display: none }`, and ANY author rule that sets `display` beats it.
Both views use flex and grid everywhere, so every element they toggle this way
is one class name away from never disappearing.

It happened. `.chip` is `display:flex`, so the red "awaiting a bed" chip on
the ship was on screen permanently: over an empty quarantine, before a
scenario had started, all through the demo. The server said `awaiting_bed: 0`
the whole time. Nothing threw and no test read the page, so it was found the
way the handover says these are always found: by opening it.

`#fallback[hidden]` had already been patched one element at a time. This test
asks for the rule that covers every element instead, in both views.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

HIDDEN_WINS = re.compile(r"(?m)^\s*\[hidden\]\s*\{\s*display\s*:\s*none\s*!important\s*;?\s*\}")


@pytest.mark.parametrize("sheet", ["web/ship.css", "web/style.css"])
def test_hidden_beats_every_display_rule(sheet: str):
    css = (ROOT / sheet).read_text(encoding="utf-8")
    assert HIDDEN_WINS.search(css), (
        f"{sheet} has no `[hidden]{{display:none !important}}`, so any element "
        "whose class sets display (flex, grid, block) ignores el.hidden and "
        "stays on screen"
    )
