"""A board that has stopped updating says so, in both views.

The worst failure this product has is a board frozen on plausible numbers, and
the browser had no way to notice one: the link chip only watched the socket,
and a socket can stay open while nothing useful arrives, or while every frame
that does arrive throws half way through rendering.

Checked live on the demo laptop by suspending the station process for ten
seconds: the chip went red, "No update for 3 s" up to "10 s", the numbers
dimmed, and both came back within a second of the process resuming.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

VIEWS = {"web/app.js": "web/style.css", "web/ship.js": "web/ship.css"}


def _on_board(src: str) -> str:
    m = re.search(r"function onBoard\(\w+\) \{(.*?)\n  \}\n", src, re.S)
    assert m, "no onBoard() to check"
    return m.group(1)


@pytest.mark.parametrize("view", sorted(VIEWS))
def test_a_repaint_is_stamped_only_once_it_has_finished(view: str):
    body = _on_board((ROOT / view).read_text(encoding="utf-8"))
    last = [ln.strip() for ln in body.strip().splitlines() if ln.strip()][-1]
    assert last == "lastPainted = Date.now();", (
        f"{view}: the repaint is stamped before it has finished, so a frame that "
        "throws half way through still counts as the board being alive"
    )


@pytest.mark.parametrize("view", sorted(VIEWS))
def test_the_watchdog_turns_the_chip_red_and_dims_the_numbers(view: str):
    src = (ROOT / view).read_text(encoding="utf-8")
    assert re.search(r"setInterval\(function \(\) \{\s*if \(!ws", src), f"{view}: no watchdog"
    assert 'classList.toggle("stale-feed", stale)' in src, f"{view}: nothing dims"
    css = (ROOT / VIEWS[view]).read_text(encoding="utf-8")
    assert re.search(r"\.stale-feed [^{]*\{[^}]*opacity", css), (
        f"{VIEWS[view]}: .stale-feed has no rule, so the class changes nothing"
    )


@pytest.mark.parametrize("view", sorted(VIEWS))
def test_a_warning_from_the_station_reaches_the_screen(view: str):
    """A skipped scenario step is published as an event of kind "warning".

    Neither view rendered events at all, so the notice existed only on the wire
    and in the server's log, where nobody running a demo would see it.
    """
    src = (ROOT / view).read_text(encoding="utf-8")
    assert re.search(r'\.type === "event" && \w+\.kind === "warning"', src), (
        f"{view} drops the station's warnings"
    )


def test_a_lost_graphics_context_says_so_and_offers_the_board():
    """A driver reset, a sleep and resume, a projector plugged in mid-demo.

    Nothing listened for webglcontextlost, so the ship went black and silent
    with the HUD still floating over it. Checked in a browser by forcing the
    loss with WEBGL_lose_context: the fallback now appears with the board link.
    """
    src = (ROOT / "web" / "ship.js").read_text(encoding="utf-8")
    m = re.search(r'addEventListener\("webglcontextlost", function \(e\) \{(.*?)\n  \}\);', src, re.S)
    assert m, "ship.js does not listen for a lost WebGL context"
    assert "fb.hidden = false" in m.group(1), "the loss is heard but nothing is shown"
