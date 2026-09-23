"""Render everything the station can say, once, into web/speech/.

Run this on a developer machine and commit the result. The demo laptop never
runs it and never installs Piper:

    pip install piper-tts
    python -m piper.download_voices fr_FR-siwis-medium --data-dir voices/
    python tools/render_speech.py --voice voices/fr_FR-siwis-medium.onnx
    git add web/speech && git commit

Why it works this way, in one line each:

- **Licence.** piper-tts is GPL-3.0-or-later. Importing it at runtime would
  make MedBox GPL-3. Running it offline at build time and shipping the audio
  does not, because nothing links against it and nothing distributes it. The
  SIWIS French voice is CC BY 4.0 (credit: SIWIS database, Yamagishi et al.).
- **Speed.** Nothing is synthesised on stage. Playing a line is a disk read.
- **Certainty.** `server/speech.every_clip()` computes the complete set, and
  the crew names come from a fixed seed, so the set never changes. `--check`
  compares the files on disk against it and names what is missing. There is no
  line the station can reach that nobody rendered.

Without `--voice`, it writes silent placeholders of the right length. That is
not a fallback for the demo — it is so the playback path, the queue, the
preloading and the tests all work before anybody has installed a speech
engine, and so a missing render fails as silence in a known place rather than
as a 404 nobody noticed.
"""
from __future__ import annotations

import argparse
import struct
import sys
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server.speech import every_clip  # noqa: E402

OUT = ROOT / "web" / "speech"
SAMPLE_RATE = 22050


def crew_names() -> list[str]:
    """The forty names, from the same seeded generator the station uses.

    Imported rather than hard-coded, so this file cannot drift from the crew
    the ship actually has.
    """
    from server.config import CONFIG
    from server.sensors.synthetic import ScenarioSource

    source = ScenarioSource(CONFIG.ship.crew_size)
    return [p.name for p in source.patients.values()]


def write_placeholder(path: Path, text: str) -> None:
    """Silence, roughly as long as the line would take to say.

    Real duration matters even for a placeholder: it is what proves the queue
    does not overlap two announcements, and a zero-length file would make the
    gap logic look correct when it is not.
    """
    seconds = max(0.6, len(text.split()) * 0.38)
    frames = int(SAMPLE_RATE * seconds)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(struct.pack(f"<{frames}h", *([0] * frames)))


# How a line is SAID, where that differs from how it is written. Applied to the
# synthesis only; the text the station shows and logs does not change. Found
# by transcribing every rendered clip back with the station's own speech
# model. With the French voice (fr_FR-siwis-medium, CC BY 4.0) the product
# name reads best as two words; "Zone A" needs nothing, and every trick tried
# on it ("Zone Â", "Zone Ah", "Zone Alpha") came back worse.
SPOKEN = {
    "MedBox": "Med Box",
}


def spoken(text: str) -> str:
    for written, said in SPOKEN.items():
        text = text.replace(written, said)
    return text


def is_silent(path: Path) -> bool:
    """True for a placeholder: no sample louder than the faintest hiss.

    --check used to compare file names only, so 56 files of pure silence passed
    it, were committed, and the handover described them as rendered speech.
    """
    import array

    with wave.open(str(path), "rb") as w:
        samples = array.array("h", w.readframes(w.getnframes()))
    return max((abs(s) for s in samples), default=0) < 64


def render_with_piper(voice_path: Path, clips: dict[str, str]) -> int:
    from piper import PiperVoice  # imported here: never a runtime dependency

    voice = PiperVoice.load(str(voice_path))
    written = 0
    for stem, text in sorted(clips.items()):
        target = OUT / f"{stem}.wav"
        with wave.open(str(target), "wb") as w:
            voice.synthesize_wav(spoken(text), w)
        written += 1
        print(f"  {stem}.wav  {text}")
    return written


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--voice", help="path to a Piper .onnx voice")
    ap.add_argument("--check", action="store_true",
                    help="report what is missing or unexpected, write nothing")
    args = ap.parse_args()

    clips = every_clip(crew_names())

    if args.check:
        have = {p.stem for p in OUT.glob("*.wav")} if OUT.exists() else set()
        missing = sorted(set(clips) - have)
        extra = sorted(have - set(clips))
        for stem in missing:
            print(f"  MISSING  {stem}.wav  \"{clips[stem]}\"")
        for stem in extra:
            print(f"  EXTRA    {stem}.wav  (nothing can ever play this)")
        silent = sorted(s for s in set(clips) & have if is_silent(OUT / f"{s}.wav"))
        for stem in silent:
            print(f"  SILENT   {stem}.wav  a placeholder, not speech")
        if not missing and not extra and not silent:
            print(f"All {len(clips)} clips present, and none of them silent.")
            return 0
        return 1

    OUT.mkdir(parents=True, exist_ok=True)
    if args.voice:
        path = Path(args.voice).expanduser()
        if not path.exists():
            print(f"No voice at {path}.", file=sys.stderr)
            print("  python -m piper.download_voices fr_FR-siwis-medium --data-dir voices/",
                  file=sys.stderr)
            return 1
        n = render_with_piper(path, clips)
        print(f"\nRendered {n} clips with {path.name}. Commit web/speech/.")
    else:
        for stem, text in sorted(clips.items()):
            write_placeholder(OUT / f"{stem}.wav", text)
        print(f"Wrote {len(clips)} SILENT placeholders to web/speech/.")
        print("The station will run and stay silent. Pass --voice to render for real.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
