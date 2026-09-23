"""The kill moment must survive an Ollama this window cannot stop.

On the demo machine the installer left an ollama.exe running with elevated
rights. Stop-Process on it prints a red stack, the server keeps answering, and
the presenter has just said "I killed it". The script now skips what it cannot
stop, names the PID, and checks both the installed port and the bundle's, and
preflight refuses to say the machine is ready while such a process exists.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KILL = ROOT / "tools" / "assistant.ps1"
PREFLIGHT = ROOT / "tools" / "preflight.ps1"


def test_the_scripts_stay_ascii():
    for script in (KILL, PREFLIGHT):
        raw = script.read_bytes()
        bad = [b for b in raw if b > 127]
        assert not bad, (
            f"{script.name} has non-ASCII bytes; PowerShell 5.1 decodes a "
            "BOM-less .ps1 with the system code page"
        )


def test_stop_names_what_it_cannot_kill_instead_of_a_stack():
    src = KILL.read_text(encoding="ascii")
    assert "if (-not $p.Path)" in src, "an elevated process is recognised by its unreadable path"
    stop_block = src.split('$Action -eq "stop"', 1)[1].split('$Action -eq "start"', 1)[0]
    assert "-ErrorAction SilentlyContinue" in stop_block
    assert "elevated rights" in stop_block


def test_stop_checks_the_bundle_port_too():
    src = KILL.read_text(encoding="ascii")
    assert "11555" in src and "11434" in src
    assert "Get-AnsweringPorts" in src


def test_start_can_relaunch_the_bundled_assistant():
    src = KILL.read_text(encoding="ascii")
    assert "runtime\\ollama\\ollama.exe" in src
    assert "OLLAMA_MODELS" in src and "OLLAMA_HOST" in src


def test_preflight_never_calls_the_cli_while_the_server_is_down():
    """On Windows the Ollama CLI starts the tray app when no server answers,
    the app inherits the script's stdout, and `| Out-String` waits forever.
    The port is probed first, and the CLI is only reached when it answers."""
    src = PREFLIGHT.read_text(encoding="ascii")
    probe = src.index("Test-Port 11434")
    cli = src.index("& $ollama --version")
    assert probe < cli, "probe the port before the first CLI call"
    assert "function Test-Port" in src


def test_preflight_blocks_on_an_elevated_ollama():
    src = PREFLIGHT.read_text(encoding="ascii")
    assert "droits eleves" in src
    before = src.split("droits eleves", 1)[0]
    assert "Fail (" in before[-400:], "an elevated ollama must be a blocker, not a warning"
