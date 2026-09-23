"""The portable Python must not import from the host's per-user site-packages.

Found on the build machine, not in code review: the embeddable runtime, with
`import site` enabled in its ._pth, put the user's roaming site-packages on
sys.path. A bundle that resolves one import there works on the laptop that
built it and on no other. The launcher now passes -s and sets PYTHONNOUSERSITE,
and the builder's smoke test runs the runtime the same way and refuses one
that still leaks. These pin both, so neither can be "simplified" away.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "launcher" / "MedBox.Launcher" / "Program.cs"
BUILDER = ROOT / "tools" / "build-portable.ps1"


def test_the_launcher_starts_python_without_the_user_site():
    src = LAUNCHER.read_text(encoding="utf-8")
    assert '["-s", entry,' in src, "the launcher must start medbox.py with -s"
    assert '["PYTHONNOUSERSITE"] = "1"' in src, "children of the station inherit the same rule"


def test_the_builder_smokes_the_runtime_the_way_the_launcher_runs_it():
    src = BUILDER.read_text(encoding="utf-8")
    assert "& $python -s $entry --check" in src
    assert "site.ENABLE_USER_SITE" in src, "the smoke test must refuse a runtime that sees the host"


def test_dash_s_is_what_closes_the_hole():
    """The mechanism itself, on the interpreter running the suite: -s empties
    the user site from sys.path. If a future Python changed that, the launcher's
    flag would be the wrong one and this is where it would show."""
    probe = (
        "import site, sys; "
        "print(site.ENABLE_USER_SITE, any('site-packages' in p and 'Roaming' in p for p in sys.path))"
    )
    out = subprocess.run([sys.executable, "-s", "-c", probe], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert out.stdout.split() == ["False", "False"]
