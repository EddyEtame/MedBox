"""The flat board can be clicked and tabbed while it repaints ten times a second.

It rebuilds every row with innerHTML on every frame. A click needs the same
element under the pointer when the button goes down and when it comes up, so a
rebuild in between swallowed it: a row pressed during a demo sometimes did not
open. And keyboard focus went with the old rows, 100 ms after it arrived.

Checked in a real browser after the fix: five clicks on five rows opened five
crew members, and focus stayed on its row through fifteen repaints.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = (ROOT / "web" / "app.js").read_text(encoding="utf-8")


def test_a_row_is_selected_on_press_not_on_click():
    assert 'el("rows").addEventListener("pointerdown"' in APP, (
        "rows are selected on click, which a repaint between press and release swallows"
    )
    assert 'el("rows").addEventListener("click"' not in APP


def test_focus_survives_the_repaint():
    m = re.search(r"function renderRows\(\) \{(.*?)\n  \}\n", APP, re.S)
    assert m, "no renderRows() to check"
    body = m.group(1)
    swap = body.index("host.innerHTML = html;")
    assert "document.activeElement" in body[:swap], "focus is not noted before the rows are replaced"
    assert ".focus()" in body[swap:], "focus is not put back after the rows are replaced"
