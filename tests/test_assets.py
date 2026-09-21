"""The quiet failure this guards against, reproduced.

A developer unzips a model into `models/`, watches everything work, commits,
pushes, and finds out on the day that the weights were never in the repo:
`.gitignore` excludes `models/` and `*.gguf`, nothing errored, `git status`
was clean. So the check has to be a real check, and a file that arrived
truncated or as a Git LFS pointer has to be caught rather than handed to the
model loader.
"""
from __future__ import annotations

import hashlib
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.assets import (  # noqa: E402
    SPEECH_FILES,
    _lone_top_folder,
    install_from,
    read_manifest,
    unpack,
    verify,
)


def _write(path: Path, data: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def test_a_correct_file_verifies(tmp_path):
    f = tmp_path / "model.gguf"
    want = _write(f, b"weights" * 500)
    good, why = verify({"sha256": want}, f)
    assert good and "verified" in why


def test_a_truncated_file_is_caught(tmp_path):
    """A half-finished download and a complete one look identical in `ls`."""
    f = tmp_path / "model.gguf"
    want = _write(f, b"weights" * 500)
    f.write_bytes(b"weights" * 200)
    good, why = verify({"sha256": want}, f)
    assert not good and "mismatch" in why


def test_a_git_lfs_pointer_is_named_as_such(tmp_path):
    """The commonest way a 4 GB file turns into 130 bytes with the right name.

    An error saying "hash mismatch" sends somebody re-downloading. An error
    naming LFS sends them to the actual problem.
    """
    f = tmp_path / "model.gguf"
    f.write_bytes(
        b"version https://git-lfs.github.com/spec/v1\noid sha256:abc\nsize 4000000\n"
    )
    good, why = verify({"sha256": "0" * 64}, f)
    assert not good and "LFS" in why


def test_a_missing_file_is_missing_not_broken(tmp_path):
    good, why = verify({"sha256": "0" * 64}, tmp_path / "nope.gguf")
    assert not good and why == "missing"


def test_a_file_with_no_recorded_hash_does_not_claim_to_be_verified(tmp_path):
    """Saying "verified" about something nobody checked is the one thing this
    module must never do."""
    f = tmp_path / "voice.onnx"
    _write(f, b"x" * 100)
    good, why = verify({}, f)
    assert good
    assert "verified" not in why and "not recorded" in why


def test_installing_from_a_drive_needs_no_network(tmp_path):
    usb = tmp_path / "usb"
    dest_root = tmp_path / "repo"
    want = _write(usb / "model.gguf", b"weights" * 500)
    asset = {"path": "models/model.gguf", "sha256": want}
    dest = dest_root / asset["path"]
    assert install_from(asset, usb, dest) is True
    assert verify(asset, dest)[0] is True


def test_a_drive_missing_the_file_says_so_rather_than_half_installing(tmp_path):
    usb = tmp_path / "usb"
    usb.mkdir()
    dest = tmp_path / "repo" / "models" / "model.gguf"
    assert install_from({"path": "models/model.gguf"}, usb, dest) is False
    assert not dest.exists()


def test_no_part_file_survives_a_successful_install(tmp_path):
    """An interrupted copy must never leave something shaped like a finished
    file, because everything downstream would treat it as real."""
    usb = tmp_path / "usb"
    _write(usb / "model.gguf", b"weights" * 500)
    dest = tmp_path / "repo" / "models" / "model.gguf"
    install_from({"path": "models/model.gguf"}, usb, dest)
    assert list(dest.parent.glob("*.part")) == []


def test_the_manifest_parses_whatever_is_in_config_today():
    """Zero assets is a valid state and must not throw: the whole product runs
    without weights, which is the point of the stand-in."""
    assert isinstance(read_manifest(), list)


def test_weights_stay_out_of_git():
    """If this ever fails, someone is about to push a blob GitHub will reject
    and the demo laptop will clone a repo with no model in it."""
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for rule in ("models/", "*.gguf"):
        assert rule in ignored, f"{rule} must stay in .gitignore"


# ----------------------------------------------------- the model on a stick

def _zip(path: Path, members: dict[str, bytes]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        for name, data in members.items():
            z.writestr(name, data)
    return path


def _unpack_into(archive: Path, dest: Path) -> bool:
    """unpack() resolves against the repo root, so give it a path it can."""
    import tools.assets as assets

    real, assets.ROOT = assets.ROOT, dest.parent
    try:
        return assets.unpack({"path": str(archive), "unpack": dest.name}, archive)
    finally:
        assets.ROOT = real


def test_a_zip_of_a_folder_lands_in_the_folder_and_not_inside_itself(tmp_path):
    """Found on a real drive. `zip -r model.zip model/` stores every path with
    the folder still on the front, so extracting it into models/x produced
    models/x/x and the loader found nothing. Both ways of zipping a folder are
    natural and people use both, so both have to land identically."""
    z = _zip(tmp_path / "m.zip", {f"faster-whisper-base/{f}": b"x" for f in SPEECH_FILES})
    dest = tmp_path / "repo" / "faster-whisper-base"
    assert _unpack_into(z, dest)
    for f in SPEECH_FILES:
        assert (dest / f).exists(), f"{f} did not land at the top of the folder"
    assert not (dest / "faster-whisper-base").exists(), "the folder nested inside itself"


def test_a_zip_made_from_inside_the_folder_lands_the_same_way(tmp_path):
    z = _zip(tmp_path / "m.zip", {f: b"x" for f in SPEECH_FILES})
    dest = tmp_path / "repo" / "faster-whisper-base"
    assert _unpack_into(z, dest)
    for f in SPEECH_FILES:
        assert (dest / f).exists()


def test_one_stray_file_does_not_get_mistaken_for_a_wrapper_folder(tmp_path):
    """Stripping a shared prefix is only right when it really is a folder
    holding everything. A zip of a single file must not lose its name."""
    assert _lone_top_folder(["model.bin"]) == ""
    assert _lone_top_folder(["m/a", "m/b"]) == "m"
    assert _lone_top_folder(["m/a", "n/b"]) == ""


def test_a_zip_cannot_write_outside_where_it_was_put(tmp_path):
    """The oldest archive trick there is, and this one arrives on a stick that
    has been in somebody else's laptop."""
    dest = tmp_path / "repo" / "models"
    for name in ("../../escape.txt", "m/../../escape.txt", "/tmp/escape.txt"):
        z = _zip(tmp_path / "evil.zip", {name: b"pwned", "config.json": b"{}"})
        assert _unpack_into(z, dest) is False, f"{name} was not blocked"
        assert not (tmp_path / "escape.txt").exists()
        assert not (tmp_path / "repo" / "escape.txt").exists()


def test_the_speech_model_is_named_by_the_files_the_loader_needs():
    """These are read from faster-whisper's own allow_patterns. If the library
    ever stops looking for one of them, "present" starts meaning nothing."""
    assert "model.bin" in SPEECH_FILES
    assert "config.json" in SPEECH_FILES
    assert "tokenizer.json" in SPEECH_FILES


def test_the_error_the_server_shows_names_a_command_that_does_something():
    """server/voice.py tells an operator to run tools/assets.py. For a long
    while that printed "there is nothing large to fetch" and stopped, which is
    a dead end dressed as an instruction."""
    voice = (ROOT / "server" / "voice.py").read_text(encoding="utf-8")
    assert "tools/assets.py" in voice
    assets_src = (ROOT / "tools" / "assets.py").read_text(encoding="utf-8")
    assert "fetch_speech" in assets_src, "assets.py does not fetch the speech model"
    assert "download_model" in assets_src, "assets.py has no way to get the weights"


def test_the_speech_dependencies_are_declared_somewhere_installable():
    """They are not in requirements.txt on purpose: a failed optional wheel
    must never fail the install that makes the demo work. But undeclared is a
    different thing from optional, and undeclared is how it was."""
    req = ROOT / "requirements-speech.txt"
    assert req.exists(), "nothing declares faster-whisper"
    text = req.read_text(encoding="utf-8")
    for pkg in ("faster-whisper", "ctranslate2", "av"):
        assert pkg in text, f"{pkg} is not declared"
    assert "==" in text, "the speech dependencies are not pinned"
    core = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert "faster-whisper" not in core, (
        "faster-whisper is in requirements.txt, so a failed optional wheel now "
        "fails the whole setup"
    )
    setup = (ROOT / "setup.py").read_text(encoding="utf-8")
    assert "requirements-speech.txt" in setup, "setup.py never installs them"


def test_the_installer_and_the_server_agree_on_what_a_model_is():
    """Two places decide whether a speech model is present: the installer that
    puts it there and the server that offers the button. If they drift, one of
    them is lying — either the button appears over a half-copied model and
    fails on the first press, or the installer reports success on something the
    server will refuse to load."""
    from server.voice import MODEL_FILES

    assert set(MODEL_FILES) == set(SPEECH_FILES), (
        "server/voice.py and tools/assets.py disagree about what a usable "
        f"speech model contains: {sorted(MODEL_FILES)} vs {sorted(SPEECH_FILES)}"
    )


def test_a_half_copied_model_is_not_offered_as_a_working_microphone(tmp_path):
    """A button that appears and then fails is worse than one that was never
    offered, and a directory that exists is not a model."""
    from server.voice import MODEL_FILES, Transcriber

    half = tmp_path / "faster-whisper-base"
    half.mkdir()
    (half / MODEL_FILES[0]).write_text("{}", encoding="utf-8")
    t = Transcriber(half)
    assert t.available is False
    assert "incomplete" in (t.last_error or "")
    assert "tools/assets.py" in (t.last_error or ""), "the message names no way out"


# ------------------------------------- the commands we tell people to type

def test_both_copies_of_the_command_helper_agree():
    """tools/assets.py spells this out rather than importing it, so that the
    script you run when the install is broken does not itself depend on the
    install. Two copies drift unless something checks."""
    from server.config import python_command as from_server
    from tools.assets import python_command as from_tools

    assert from_server("tools/assets.py") == from_tools("tools/assets.py")


def test_the_command_we_print_names_the_virtual_environment():
    """`python tools/assets.py` runs an interpreter with none of the
    dependencies. It reports faster-whisper as missing, the person installs it
    with the wrong pip into the wrong place, and the server still says the
    model is not there. A command that cannot work is worse than no command."""
    from server.config import python_command

    cmd = python_command("tools/assets.py")
    assert ".venv" in cmd, f"{cmd!r} does not name the virtual environment"
    assert not cmd.startswith("python "), f"{cmd!r} is the bare interpreter"


def test_the_server_tells_an_operator_a_command_that_can_actually_run():
    from server.voice import Transcriber

    t = Transcriber(ROOT / "models" / "definitely-not-here")
    assert t.available is False
    assert ".venv" in (t.last_error or ""), (
        f"the server says {t.last_error!r}, which sends a person to an "
        "interpreter that has none of the dependencies"
    )


def test_running_it_with_the_wrong_interpreter_is_detected():
    """This test runs under the venv, so in_venv() must say so. If this fails
    the guard is inverted, and every correct invocation gets refused."""
    from tools.assets import in_venv

    assert in_venv() is True, (
        "in_venv() does not recognise the interpreter running the test suite. "
        "Note a venv's python is a SYMLINK to the system one, so any check "
        "that resolves sys.executable walks back out of the venv."
    )
