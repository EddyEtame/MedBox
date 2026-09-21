"""Get the large files onto a machine, including one with no network.

Model weights, a speech model, an inference binary: none of these can live in
git. GitHub rejects any blob over 100 MB, and `.gitignore` already excludes
`models/` and `*.gguf` for good reason. So a fresh clone on the demo laptop
has the whole program and none of the things that make it talk.

That is the failure this file exists to prevent, and the shape of it is worth
spelling out because it is quiet: a developer unzips a model into `models/`,
watches everything work, commits, pushes, and finds out on Friday that the
weights were never in the repo. Nothing errored. `git status` was clean. The
demo laptop clones and the assistant simply is not there.

Three ways in, in the order you should want them:

    python tools/assets.py --from /media/usb/medbox-assets
    python tools/assets.py                 # download, if there is a network
    python tools/assets.py --check         # is this machine ready?

The USB path is first on purpose. A lecture theatre is the least reliable
network either of us will ever stand in, and "the model is a file we carried
in" is the property you want on the day. Everything is verified by SHA-256
whichever way it arrived, because a truncated download and a complete one look
identical until the moment you ask the model a question.

The manifest lives in config.toml under [[assets]], so adding a file is a
config change rather than a code change:

    [[assets]]
    name = "qwen2.5-3b-instruct-q4_k_m.gguf"
    path = "models/qwen2.5-3b-instruct-q4_k_m.gguf"
    sha256 = "..."
    url = "https://..."
    why = "The language model. Without it the assistant does not start."
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import urllib.error
import urllib.request
import warnings
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENV = ROOT / ".venv"
CHUNK = 1 << 20


def python_command(script: str) -> str:
    """The command a person should actually type to run this.

    Spelled out here rather than imported from server.config, because this file
    stays free of project imports: it is the thing you run when the install is
    incomplete, and importing a module that parses config.toml would make it
    fail for a reason that has nothing to do with the files it fetches. A test
    asserts this agrees with server.config.python_command.
    """
    if sys.platform.startswith("win"):
        return f".venv\\Scripts\\python {script}"
    return f".venv/bin/python {script}"


def in_venv() -> bool:
    """Is the interpreter running this the one that has the dependencies?

    By `sys.prefix`, not by the path of `sys.executable`. A venv's `python` is
    a symlink to the system interpreter, so resolving it walks straight back
    out of the venv and every check based on the path says no — including for
    the correct interpreter. `sys.prefix` is the venv directory itself and
    `sys.base_prefix` is the system one, which is what a venv actually means.
    """
    try:
        return Path(sys.prefix).resolve() == VENV.resolve()
    except OSError:
        return False

GREEN, RED, AMBER, DIM, OFF = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"
if not sys.stdout.isatty():
    GREEN = RED = AMBER = DIM = OFF = ""


def ok(m: str) -> None:
    print(f"  {GREEN}✓{OFF} {m}")


def bad(m: str) -> None:
    print(f"  {RED}✗{OFF} {m}")


def note(m: str) -> None:
    print(f"    {DIM}{m}{OFF}")


def read_manifest() -> list[dict]:
    """Parse [[assets]] out of config.toml.

    Hand-rolled rather than tomllib, because setup.py already reads this file
    the same way to stay runnable on a Python that predates tomllib, and one
    parser in the project is better than two that can disagree.
    """
    path = ROOT / "config.toml"
    if not path.exists():
        return []
    assets: list[dict] = []
    current: dict | None = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("[[assets]]"):
            current = {}
            assets.append(current)
            continue
        if line.startswith("[") and not line.startswith("[["):
            current = None
            continue
        if current is None or "=" not in line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        current[key.strip()] = value.strip().strip('"').strip("'")
    return [a for a in assets if a.get("path")]


def _lone_top_folder(names: list[str]) -> str:
    """The single directory every member sits inside, or "".

    There are two natural ways to zip a folder and people use both:

        zip -r model.zip model/     -> every path starts "model/"
        cd model && zip -r ../model.zip .   -> paths start at the contents

    Extracting the first into models/faster-whisper-base produces
    models/faster-whisper-base/faster-whisper-base, which loads nothing. Found
    by making a zip the obvious way and watching it fail. So the shared leading
    folder is stripped when there is exactly one, which makes both zips land
    identically.
    """
    tops = {n.split("/", 1)[0] for n in names if n and not n.startswith("/")}
    if len(tops) != 1:
        return ""
    top = tops.pop()
    # Only strip it if it really is a folder containing everything, rather than
    # a single file that happens to be the only member. A zip holding just
    # model.bin shares "model.bin" as its one leading component, and stripping
    # that would leave an empty path and silently drop the file — which is the
    # failure this whole script exists to prevent, arriving by another door.
    inside = [n for n in names if n.startswith(top + "/") and n != top + "/"]
    if not inside:
        return ""
    return top if all(n == top or n.startswith(top + "/") for n in names) else ""


def unpack(asset: dict, archive: Path) -> bool:
    """Extract a zip into the directory the asset declares.

    A model is a folder, not a file, so on a USB stick it travels as a zip. The
    extraction is checked member by member: a zip that writes outside its
    destination is the oldest archive trick there is, and this one arrives from
    a stick that has been in somebody else's laptop.
    """
    dest = (ROOT / asset["unpack"]).resolve()
    dest.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(archive) as z:
            names = z.namelist()
            strip = _lone_top_folder(names)
            for member in names:
                rel = member[len(strip) + 1:] if strip else member
                if not rel:
                    continue
                target = (dest / rel).resolve()
                if target != dest and dest not in target.parents:
                    bad(f"{asset['path']} tries to write outside {asset['unpack']}: {member}")
                    return False
                if member.endswith("/"):
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(member) as src, target.open("wb") as out:
                    shutil.copyfileobj(src, out)
    except (zipfile.BadZipFile, OSError) as exc:
        bad(f"{asset['path']} would not unpack: {exc}")
        return False
    return True


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


def verify(asset: dict, path: Path) -> tuple[bool, str]:
    if not path.exists():
        return False, "missing"
    want = (asset.get("sha256") or "").lower()
    if not want:
        # No recorded hash yet. Say so rather than implying it was checked.
        return True, f"present, {path.stat().st_size / 1e6:.0f} MB, hash not recorded"
    got = digest(path)
    if got == want:
        return True, f"verified, {path.stat().st_size / 1e6:.0f} MB"
    # The commonest cause by a distance is Git LFS: a repo that stores the file
    # as a pointer hands you a 130-byte text file with the right name.
    if path.stat().st_size < 1024:
        head = path.read_bytes()[:40]
        if b"version https://git-lfs" in head:
            return False, "this is a Git LFS pointer, not the file itself"
    return False, f"hash mismatch (got {got[:16]}…, want {want[:16]}…)"


def install_from(asset: dict, source_dir: Path, dest: Path) -> bool:
    candidate = source_dir / asset["path"]
    if not candidate.exists():
        candidate = source_dir / Path(asset["path"]).name
    if not candidate.exists():
        bad(f"{asset['path']} not found on the drive")
        note(f"expected {source_dir / Path(asset['path']).name}")
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Copy to a temporary name and rename, so an interrupted copy never leaves
    # something that looks like a finished file.
    staging = dest.with_suffix(dest.suffix + ".part")
    shutil.copyfile(candidate, staging)
    staging.replace(dest)
    return True


def download(asset: dict, dest: Path) -> bool:
    url = asset.get("url")
    if not url:
        bad(f"{asset['path']} has no url in config.toml, so it can only come from a drive")
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    staging = dest.with_suffix(dest.suffix + ".part")
    try:
        with urllib.request.urlopen(url, timeout=60) as r, staging.open("wb") as out:
            total = int(r.headers.get("Content-Length") or 0)
            seen = 0
            while chunk := r.read(CHUNK):
                out.write(chunk)
                seen += len(chunk)
                if total:
                    print(f"\r    {seen / 1e6:.0f} / {total / 1e6:.0f} MB", end="", flush=True)
            if total:
                print()
    except (urllib.error.URLError, OSError) as exc:
        staging.unlink(missing_ok=True)
        bad(f"{asset['path']}: {exc}")
        note("If there is no network here, copy the assets to a USB drive and use --from.")
        return False
    staging.replace(dest)
    return True



# --------------------------------------------------------------- speech model
#
# The speech model is not a file with a URL and a hash. It is a directory of
# five files on the Hugging Face Hub, and faster-whisper ships the function
# that fetches it correctly. Using that function rather than five hand-written
# URLs matters: the file list below is read from faster-whisper's own
# `allow_patterns`, so it cannot drift from what the library will actually look
# for when it loads the model.
#
# The server prints "Run: python tools/assets.py" when the model is absent, so
# this is what has to make that sentence true.
SPEECH_DIR = ROOT / "models" / "faster-whisper-base"

# "base" is the size, and the smallest one that transcribes an English sentence
# reliably. tiny mishears exactly the words that matter here — it turns
# "can't breathe" into "can breathe", which is the one error this must not make.
SPEECH_SIZE = "base"

# What a loadable model directory contains. From faster_whisper.utils, which is
# the only place this list is authoritative.
SPEECH_FILES = ("config.json", "model.bin", "tokenizer.json")


def speech_present() -> bool:
    return SPEECH_DIR.is_dir() and all((SPEECH_DIR / f).exists() for f in SPEECH_FILES)


def fetch_speech(source: Path | None) -> bool:
    """Put a loadable speech model in models/faster-whisper-base.

    From a drive if one was given, otherwise from the Hub through the library's
    own downloader. Both end in the same directory, which is the one the server
    loads by path.
    """
    if speech_present():
        ok(f"speech model  {DIM}present at models/{SPEECH_DIR.name}{OFF}")
        return True

    if source:
        # On a USB stick the model is a folder, or a zip of one. Both are how a
        # person would actually carry it.
        folder = source / SPEECH_DIR.name
        archive = source / f"{SPEECH_DIR.name}.zip"
        if folder.is_dir():
            SPEECH_DIR.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(folder, SPEECH_DIR, dirs_exist_ok=True)
        elif archive.exists():
            if not unpack({"path": str(archive), "unpack": str(SPEECH_DIR.relative_to(ROOT))},
                          archive):
                return False
        else:
            bad(f"no speech model on the drive (looked for {folder.name}/ and {archive.name})")
            return False
        good = speech_present()
        if not good:
            # A half-copied model is worse than none, because the next thing to
            # look at it will try to load it.
            shutil.rmtree(SPEECH_DIR, ignore_errors=True)
            bad("speech model  incomplete, so it was removed")
            note(f"a usable copy holds {', '.join(SPEECH_FILES)}")
        else:
            ok("speech model  copied from the drive")
        return good

    try:
        from faster_whisper import download_model
    except ImportError:
        bad("faster-whisper is not installed, so the speech model cannot be fetched")
        note("Install it: pip install -r requirements-speech.txt")
        note("Or copy models/faster-whisper-base from a machine that has it and use --from.")
        return False

    print(f"  {AMBER}…{OFF} speech model  {DIM}downloading, about 140 MB{OFF}")
    try:
        # By output_dir, so it lands where server/voice.py loads it from rather
        # than in a cache the demo laptop might not carry.
        #
        # Warnings silenced because faster-whisper passes a deprecated argument
        # to huggingface_hub and the resulting paragraph lands in the middle of
        # this script's output. It is not our warning and there is nothing to
        # act on, and a person reading an installer should see what happened to
        # their files rather than somebody else's deprecation notice.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            download_model(SPEECH_SIZE, output_dir=str(SPEECH_DIR))
    except Exception as exc:
        bad(f"speech model: {type(exc).__name__}: {exc}")
        note("If there is no network here, copy models/faster-whisper-base from a")
        note("machine that has it onto a drive and re-run with --from.")
        return False
    good = speech_present()
    # Nothing is hashed here, and saying so is the point: the Hub verifies its
    # own transfers, and claiming a check that did not happen is worse than
    # admitting one did not. Once it is on disk, --record prints its hashes so
    # the copy that travels on a USB stick can be checked properly.
    (ok if good else bad)(
        f"speech model  {'downloaded, verified by the Hub' if good else 'incomplete after download'}"
    )
    return good


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--from", dest="source", metavar="DIR",
                    help="a folder or USB drive holding the assets; no network needed")
    ap.add_argument("--check", action="store_true",
                    help="report what is present and verified, change nothing")
    ap.add_argument("--record", action="store_true",
                    help="print the SHA-256 of each asset present, to paste into config.toml")
    args = ap.parse_args()

    # Running this with the wrong interpreter is the likeliest mistake there
    # is, because the server's own message used to say "python tools/assets.py"
    # and every dependency lives in .venv. Caught here and named exactly, with
    # the right command, rather than reported later as "faster-whisper is not
    # installed" — which sends a person to pip, into the wrong environment, and
    # leaves the server still saying the model is missing.
    if VENV.is_dir() and not in_venv():
        bad("this is not the MedBox virtual environment, so it cannot see the "
            "dependencies")
        note(f"Run: {python_command('tools/assets.py')}")
        note("(from the MedBox folder, the one holding setup.py)")
        return 1

    manifest = read_manifest()

    if args.record:
        # The first person to fetch an asset is the one who can record what it
        # hashed to. After that the hash is in config.toml and everyone else's
        # copy is checked against it.
        for asset in manifest:
            dest = ROOT / asset["path"]
            if dest.exists():
                print(f'  # {asset["path"]}\n  sha256 = "{digest(dest)}"')
            else:
                print(f"  # {asset['path']}: not here yet")
        # The speech model travels as a zip of its directory, so what a USB
        # copy needs checked is the zip. Print its hash if one has been made.
        zipped = SPEECH_DIR.with_suffix(".zip")
        if zipped.exists():
            print(f'  # {zipped.relative_to(ROOT)}\n  sha256 = "{digest(zipped)}"')
        if not manifest and not zipped.exists():
            print("  # Nothing present to hash yet.")
        return 0

    source = Path(args.source).expanduser().resolve() if args.source else None
    if source and not source.is_dir():
        bad(f"{source} is not a folder")
        return 1

    print(f"\nAssets for MedBox  {DIM}({len(manifest) + 1} declared){OFF}\n")
    missing: list[dict] = []

    # The speech model first, because it is the one the server names by this
    # script's own command when the microphone is unavailable.
    if args.check:
        if speech_present():
            ok(f"speech model  {DIM}present at models/{SPEECH_DIR.name}{OFF}")
        else:
            bad(f"speech model  missing from models/{SPEECH_DIR.name}")
            note("Without it the microphone stays hidden. Typing is unaffected.")
            missing.append({"path": f"models/{SPEECH_DIR.name}",
                            "why": "Hold-to-speak. Typing works without it."})
    elif not fetch_speech(source):
        missing.append({"path": f"models/{SPEECH_DIR.name}",
                        "why": "Hold-to-speak. Typing works without it."})
    for asset in manifest:
        dest = ROOT / asset["path"]
        good, why = verify(asset, dest)
        if good:
            ok(f"{asset['path']}  {DIM}{why}{OFF}")
            continue
        if args.check:
            bad(f"{asset['path']}  {why}")
            if asset.get("why"):
                note(asset["why"])
            missing.append(asset)
            continue

        print(f"  {AMBER}…{OFF} {asset['path']}  {DIM}{why}{OFF}")
        got = install_from(asset, source, dest) if source else download(asset, dest)
        if not got:
            missing.append(asset)
            continue
        good, why = verify(asset, dest)
        if good and asset.get("unpack") and not unpack(asset, dest):
            good, why = False, "downloaded but would not unpack"
        (ok if good else bad)(f"{asset['path']}  {why}")
        if not good:
            # A file that arrived wrong is worse than one that did not arrive,
            # because everything downstream will treat it as real.
            dest.unlink(missing_ok=True)
            note("removed it, so nothing downstream mistakes it for the real file")
            missing.append(asset)

    print()
    if not missing:
        print(f"{GREEN}Everything is here and verified.{OFF}\n")
        return 0

    print(f"{RED}{len(missing)} asset(s) still missing.{OFF}")
    for asset in missing:
        print(f"  · {asset['path']}" + (f"  — {asset['why']}" if asset.get("why") else ""))
    print("\nMedBox still starts without these, and that is the whole design.")
    print("Vitals, NEWS2, quarantine, the board and the 3D console use none of")
    print("them. What goes quiet is the assistant, and the microphone hides")
    print("itself; typing a symptom still works and still reaches triage.")
    print("Run tools/fake_ollama.py to exercise the assistant path with no weights.\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
