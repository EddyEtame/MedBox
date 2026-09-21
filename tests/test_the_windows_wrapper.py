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
