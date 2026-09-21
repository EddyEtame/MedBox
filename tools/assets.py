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
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHUNK = 1 << 20

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


def unpack(asset: dict, archive: Path) -> bool:
    """Extract a zip into the directory the asset declares.

    A speech model is a folder, not a file, so it travels as a zip. The
    extraction is checked member by member: a zip that writes outside its
    destination is the oldest archive trick there is, and this one arrives
    from a USB stick that has been in somebody else's laptop.
    """
    dest = ROOT / asset["unpack"]
    dest.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(archive) as z:
            for member in z.namelist():
                target = (dest / member).resolve()
                if not str(target).startswith(str(dest.resolve())):
                    bad(f"{asset['path']} tries to write outside {asset['unpack']}: {member}")
                    return False
            z.extractall(dest)
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--from", dest="source", metavar="DIR",
                    help="a folder or USB drive holding the assets; no network needed")
    ap.add_argument("--check", action="store_true",
                    help="report what is present and verified, change nothing")
    ap.add_argument("--record", action="store_true",
                    help="print the SHA-256 of each asset present, to paste into config.toml")
    args = ap.parse_args()

    manifest = read_manifest()
    if not manifest:
        print("No [[assets]] in config.toml, so there is nothing large to fetch.")
        print("MedBox runs without this: the stand-in assistant needs no weights.")
        return 0

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
        return 0

    source = Path(args.source).expanduser().resolve() if args.source else None
    if source and not source.is_dir():
        bad(f"{source} is not a folder")
        return 1

    print(f"\nAssets for MedBox  {DIM}({len(manifest)} declared){OFF}\n")
    missing: list[dict] = []
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
    print("\nMedBox still starts without these. Vitals, NEWS2, quarantine, the board")
    print("and the 3D console do not use them; the assistant is what goes quiet.")
    print("Run tools/fake_ollama.py to exercise the assistant path with no weights.\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
