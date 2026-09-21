"""setup.ps1, checked by a PowerShell rather than by reading it.

This file exists because the Windows wrapper broke on a real machine in a way
that reading it did not reveal, and the fix could not be tested on the
developer's Linux box. A wrapper that will not parse is a wrapper that fails
at the worst moment, on somebody else's laptop, with an error about line 12.

So: if any PowerShell is present, use its own parser. On Windows that is the
5.1 the wrapper actually targets, which is the best possible place for this to
run. Everywhere else the test skips rather than pretending to have checked.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SCRIPT = ROOT / "setup.ps1"


def _shell() -> str | None:
    """Any PowerShell will do for a parse check. pwsh first: on Windows both
    exist and the newer one gives better diagnostics."""
    for name in ("pwsh", "powershell"):
        found = shutil.which(name)
        if found:
            return found
    return None


SHELL = _shell()
needs_powershell = pytest.mark.skipif(
    SHELL is None, reason="no PowerShell on this machine; nothing to parse with"
)


@needs_powershell
def test_the_wrapper_parses():
    """A syntax error here is invisible until somebody runs it on Windows."""
    probe = (
        "$errors = $null; $tokens = $null; "
        "$null = [System.Management.Automation.Language.Parser]::ParseFile("
        f"'{SCRIPT}', [ref]$tokens, [ref]$errors); "
        "if ($errors.Count -gt 0) { "
        "$errors | ForEach-Object { "
        "Write-Output ('line ' + $_.Extent.StartLineNumber + ': ' + $_.Message) }; "
        "exit 1 } "
        "Write-Output 'ok'"
    )
    r = subprocess.run(
        [SHELL, "-NoProfile", "-Command", probe],
        capture_output=True, text=True, timeout=120,
    )
    assert r.returncode == 0, f"setup.ps1 does not parse:\n{r.stdout}{r.stderr}"


def test_the_wrapper_exists_and_hands_over_to_setup_py():
    """Read-only, so it runs everywhere including CI on Linux."""
    assert SCRIPT.exists(), "setup.ps1 is missing; Windows has no way in"
    body = "\n".join(
        ln for ln in SCRIPT.read_text(encoding="utf-8").splitlines()
        if not ln.strip().startswith("#")
    )
    assert "setup.py" in body, "the wrapper no longer runs setup.py"
    assert "$PSScriptRoot" in body, (
        "the wrapper does not move to its own folder, so running it by full "
        "path from somewhere else would set up the wrong directory"
    )


def test_the_wrapper_is_pure_ascii():
    """Windows PowerShell 5.1 decodes a BOM-less .ps1 using the system ANSI
    code page, not UTF-8. A UTF-8 em dash then arrives as three cp1252
    characters, one of which is a curly quote the tokenizer can take an
    interest in. Inside a comment that is harmless; one line higher it is not.
    Staying ASCII sidesteps the whole question."""
    raw = SCRIPT.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), "unexpected BOM; the test below assumes none"
    bad = [(n, ln) for n, ln in enumerate(raw.decode("utf-8").splitlines(), 1)
           if any(ord(c) > 127 for c in ln)]
    assert not bad, (
        "setup.ps1 has non-ASCII characters, which PowerShell 5.1 will decode "
        "as cp1252:\n  " + "\n  ".join(f"line {n}: {ln.strip()}" for n, ln in bad)
    )


def test_the_wrapper_takes_one_match_and_only_a_real_executable():
    """Get-Command can return several matches for a name, and a profile-defined
    function or alias has an empty .Source. Either turns $exe into something
    the hand-off cannot invoke."""
    body = "\n".join(
        ln for ln in SCRIPT.read_text(encoding="utf-8").splitlines()
        if not ln.strip().startswith("#")
    )
    assert "-CommandType Application" in body, (
        "setup.ps1 accepts non-executables as an interpreter"
    )
    lookup = [ln for ln in body.splitlines() if "Get-Command" in ln and "$cand" in ln]
    assert lookup, "setup.ps1 no longer looks candidates up with Get-Command"
    for ln in lookup:
        assert "Select-Object -First 1" not in ln, (
            "setup.ps1 is back to testing only the first match. The Store stubs "
            "in %LOCALAPPDATA%\\Microsoft\\WindowsApps are on the user PATH by "
            "default and often sit ahead of a python.org install, so the first "
            "match is the one that fails and the real interpreter is second."
        )
        assert ln.strip().startswith("foreach"), (
            "setup.ps1 no longer probes every match for a name"
        )
    assert "-LiteralPath" in body, (
        "Set-Location -Path treats [ and ] as wildcards, so a clone under a "
        "folder like 'MedBox [old]' would not resolve"
    )
    assert "$global:LASTEXITCODE = $null" in body, (
        "$LASTEXITCODE is session state; without clearing it a stale 0 reports "
        "a setup that never ran as a success"
    )


# --------------------------------------------------------------------------
# Running it, not reading it.
#
# Every test above this line is a text check, and every one of them passed on
# the day `py -3` resolved to 3.9.13 on the owner's machine, the wrapper
# committed to it, and setup stopped at step 1 pointing at python.org for a
# Python that was already installed as 3.11.9. Reading the script cannot catch
# that. Running it against interpreters we control can.
#
# The stand-ins are shell scripts, so this needs a POSIX shell as well as a
# PowerShell. On Windows -- where the real thing runs, and where the real
# interpreters are -- it skips.
runs_fakes = pytest.mark.skipif(
    SHELL is None or sys.platform.startswith("win"),
    reason="needs both a PowerShell and a POSIX shell to plant stand-in interpreters",
)

STUB = """#!/bin/sh
code=""
next=0
for a in "$@"; do
  if [ $next -eq 1 ]; then code="$a"; next=0; fi
  if [ "$a" = "-c" ]; then next=1; fi
done
if [ -n "$code" ]; then
  exec {real} -c "import sys
sys.version_info = ({major}, {minor}, 0, 'final', 0)
sys.version = '{major}.{minor}.0 (stand-in)'
$code"
fi
echo "{label}"
exit 0
"""


def plant(folder: Path, name: str, major: int, minor: int) -> None:
    exe = folder / name
    exe.write_text(
        STUB.format(real=sys.executable, major=major, minor=minor,
                    label=f"CHOSE {name} {major}.{minor}"),
        encoding="utf-8",
    )
    exe.chmod(0o755)


def run_wrapper(tmp_path: Path, pythons: dict[str, tuple[int, int]]):
    """Plant the given interpreters and nothing else, then run setup.ps1."""
    binx = tmp_path / "bin"
    binx.mkdir()
    for name, (major, minor) in pythons.items():
        plant(binx, name, major, minor)
    (tmp_path / "setup.ps1").write_text(SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "setup.py").write_text("print('SETUP RAN')\n", encoding="utf-8")
    return subprocess.run(
        [SHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "./setup.ps1"],
        cwd=tmp_path,
        env={"PATH": str(binx), "HOME": str(tmp_path)},
        capture_output=True, text=True, timeout=180,
    )


@runs_fakes
def test_an_old_py_launcher_does_not_win_over_a_new_python(tmp_path):
    """The owner's machine, exactly: the launcher answers 3.9 and the
    interpreter that works is on PATH under its own name."""
    r = run_wrapper(tmp_path, {"py": (3, 9), "python": (3, 11)})
    assert "CHOSE python 3.11" in r.stdout, (
        "the wrapper took the 3.9 launcher again:\n" + r.stdout + r.stderr
    )
    assert r.returncode == 0


@runs_fakes
def test_the_launcher_still_wins_when_it_is_new_enough(tmp_path):
    """The fix must not stop preferring `py`, which is the right answer on a
    healthy Windows machine and costs one process."""
    r = run_wrapper(tmp_path, {"py": (3, 12), "python": (3, 11)})
    assert "CHOSE py 3.12" in r.stdout, r.stdout + r.stderr


@runs_fakes
def test_nothing_new_enough_refuses_and_says_what_is_there(tmp_path):
    """Refusing is right. Refusing without naming the Pythons it found is how
    somebody is told to install what they already have."""
    r = run_wrapper(tmp_path, {"py": (3, 9), "python": (3, 10)})
    assert r.returncode == 1
    assert "No Python 3.11 or newer" in r.stdout
    assert "3.9.0" in r.stdout and "3.10.0" in r.stdout, (
        "the refusal does not say what it found:\n" + r.stdout
    )
    assert "SETUP RAN" not in r.stdout, "it handed over to setup.py anyway"
