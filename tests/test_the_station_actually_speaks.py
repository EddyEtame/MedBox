"""Every line the station can say is committed as speech, not silence.

All 56 clips were once placeholders: zero samples, the right length, present
under the right names. --check compared names, so it passed; the test compared
names, so it passed; and the handover said the Piper clips were rendered. On
stage, "Sound on" would have played nothing, including "The assistant has
stopped", the line the kill moment is built around.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server.speech import every_clip  # noqa: E402
from tools.render_speech import OUT, crew_names, is_silent, write_placeholder  # noqa: E402

CLIPS = sorted(every_clip(crew_names()))


@pytest.mark.parametrize("stem", CLIPS)
def test_the_clip_is_speech(stem: str):
    assert not is_silent(OUT / f"{stem}.wav"), (
        f"web/speech/{stem}.wav is silence. Render it: tools/render_speech.py --voice ..."
    )


def test_a_placeholder_is_recognised_as_silence(tmp_path):
    placeholder = tmp_path / "x.wav"
    write_placeholder(placeholder, "Zone A is now sealed.")
    assert is_silent(placeholder)
