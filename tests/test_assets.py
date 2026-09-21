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
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.assets import install_from, read_manifest, verify  # noqa: E402


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
