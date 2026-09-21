"""The rule that voice and the microphone cannot take the readings down.

Everything in this project is split into a fast track and a slow track. The
Python side of that rule is already tested: `triage.py`, `sensors/` and `db.py`
may not import from `ai/`. The browser side had no such test, and it is where
the rule is easiest to break, because in a browser a missing file is not an
import error. It is `undefined`, and `undefined.setAvailable(...)` throws
inside the WebSocket handler.

That throw is the interesting part. The socket keeps delivering frames, so
nothing looks disconnected; the handler simply dies partway down, ten times a
second, and every line below the throw stops running. The board freezes with
plausible numbers on it. Found by blocking the two files in a real browser:
fifty frames arrived and fifty errors were thrown, and the readings stopped.

So voice.js and mic.js are treated as genuinely optional, and every call into
them is guarded. This test is what keeps that true when somebody adds the
next one.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# The two views. Both stream the board over a WebSocket and both render the
# same readings, so the rule has to hold in each of them.
VIEWS = ["web/app.js", "web/ship.js"]

# The scripts that are allowed to be missing. They are additions to the
# console, not part of it: the demo laptop can lose either one and still show
# every number that matters.
OPTIONAL = ["MedBox.voice", "MedBox.mic"]

CALL = re.compile(r"MedBox\.(voice|mic)\.")


def _lines(path: str) -> list[str]:
    return (ROOT / path).read_text(encoding="utf-8").splitlines()


def _guarded(lines: list[str], i: int, ns: str) -> bool:
    """Is the call on line `i` protected?

    Two shapes count, because both are safe and both read well in place:
    a test on the same line, and an early return further up the same block.
    """
    if f"{ns})" in lines[i] or f"!{ns}" in lines[i]:
        return True
    # An early return above it, e.g. `if (!MedBox.voice) { ...; return; }`.
    # Fifteen lines is the length of the block this actually appears in, and
    # keeping it short stops an unrelated guard elsewhere in the file from
    # excusing a genuinely bare call.
    for back in lines[max(0, i - 15):i]:
        if f"!{ns}" in back and "return" in back:
            return True
    return False


@pytest.mark.parametrize("view", VIEWS)
def test_no_view_calls_an_optional_script_without_checking_it_is_there(view: str):
    lines = _lines(view)
    bare: list[str] = []
    for i, line in enumerate(lines):
        if line.lstrip().startswith("//") or line.lstrip().startswith("*"):
            continue
        m = CALL.search(line)
        if not m:
            continue
        ns = "MedBox." + m.group(1)
        if not _guarded(lines, i, ns):
            bare.append(f"{view}:{i + 1}  {line.strip()}")
    assert not bare, (
        "these call an optional script without checking it loaded, which "
        "throws inside the frame handler and freezes the readings:\n  "
        + "\n  ".join(bare)
    )


@pytest.mark.parametrize("view", VIEWS)
def test_the_optional_scripts_load_before_the_view_that_uses_them(view: str):
    """A script tag in the wrong order is the same bug with no error message.

    `app.js` and `ship.js` wire their buttons as they load, so anything they
    reach for has to already be on the page.
    """
    page = "web/index.html" if view.endswith("app.js") else "web/ship.html"
    html = (ROOT / page).read_text(encoding="utf-8")
    order = re.findall(r'<script src="/static/([\w.]+)"', html)
    assert order, f"no scripts found in {page}"
    view_name = Path(view).name
    assert view_name in order, f"{page} never loads {view_name}"
    at = order.index(view_name)
    for dep in ("voice.js", "mic.js", "assessment.js"):
        assert dep in order, f"{page} never loads {dep}"
        assert order.index(dep) < at, f"{page} loads {dep} after {view_name}"


def test_the_microphone_is_hidden_until_the_station_says_it_can_listen():
    """A button that appears and then fails is worse than no button.

    The markup ships it hidden and the server's `ears` field is what reveals
    it, so a machine with no speech model never offers one.
    """
    for page in ("web/index.html", "web/ship.html"):
        html = (ROOT / page).read_text(encoding="utf-8")
        tag = re.search(r"<button[^>]*id=\"micBtn\"[^>]*>", html)
        assert tag, f"{page} has no microphone button"
        assert "hidden" in tag.group(0), f"{page} ships the microphone button visible"


def test_nothing_in_the_browser_sends_audio_off_this_machine():
    """The Web Speech API in Chrome ships the recording to Google, which would
    quietly undo the one claim the whole project rests on."""
    js = (ROOT / "web" / "mic.js").read_text(encoding="utf-8")
    for banned in ("webkitSpeechRecognition", "SpeechRecognition("):
        assert banned not in js, f"mic.js reaches for {banned}"
    posts = re.findall(r"fetch\(\s*[\"'`]([^\"'`]+)", js)
    assert posts, "mic.js posts nowhere"
    for url in posts:
        assert url.startswith("/api/"), f"mic.js posts audio to {url}"
