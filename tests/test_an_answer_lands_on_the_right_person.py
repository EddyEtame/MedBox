"""An assessment is shown under the crew member it was asked about, or not at all.

The model takes seconds to answer on a laptop CPU. Both views used to write
the answer into whatever panel was open when it arrived, so selecting P-03,
pressing Ask and then moving to P-07 put P-03's hypotheses under P-07's name,
band and vitals. The staleness banner did not fire either, because it only
compares an assessment with the person it belongs to. Reproduced in a stub
DOM against a real /api/assess response before this was fixed.

The fix is one line of intent in each view: remember who was asked about, and
drop an answer for anybody else. This test keeps both halves of it.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _ask_ai(view: str) -> str:
    src = (ROOT / view).read_text(encoding="utf-8")
    m = re.search(r"function askAI\(\) \{(.*?)\n  \}\n", src, re.S)
    assert m, f"{view} has no askAI() to check"
    return m.group(1)


@pytest.mark.parametrize("view", ["web/app.js", "web/ship.js"])
def test_the_answer_is_pinned_to_who_was_asked_about(view: str):
    body = _ask_ai(view)
    assert re.search(r"var id = state\.selected;", body), (
        f"{view}: askAI() does not remember who it asked about"
    )
    assert 'encodeURIComponent(id)' in body, f"{view}: it asks about someone else"
    # Once in the answer path and once in the failure path.
    assert len(re.findall(r"if \(state\.selected !== id\) return;", body)) >= 2, (
        f"{view}: a late answer or failure is drawn under whoever is selected now"
    )
