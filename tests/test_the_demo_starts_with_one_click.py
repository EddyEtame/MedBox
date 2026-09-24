"""One double-click from the working copy, on a machine with Ollama installed.

Eddy, 24 Sep evening: "I just want to be able to click on it on my PC and it
opens up properly and opens the dev server." DEMARRER-LA-DEMO.cmd at the
root of the repo runs tools\demarrer.ps1: the installed Ollama is started if
silent, the station is started in that window, the browser opens when the
station answers, and closing the window stops everything.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUTTON = ROOT / "DEMARRER-LA-DEMO.cmd"
SCRIPT = ROOT / "tools" / "demarrer.ps1"


def test_the_button_and_its_script_exist_and_stay_ascii():
    button = BUTTON.read_text(encoding="ascii")
    script = SCRIPT.read_text(encoding="ascii")
    assert "tools\demarrer.ps1" in button and "pause" in button
    assert "ExecutionPolicy Bypass" in button, "a machine with a locked policy must still run it"
    assert "medbox.py" in script and ".venv\Scripts\python.exe" in script


def test_the_script_opens_the_browser_only_once_the_station_answers():
    script = SCRIPT.read_text(encoding="ascii")
    assert "function Test-Station" in script and "/api/status" in script
    start = script.index('Start-Process -FilePath $py -ArgumentList "medbox.py"')
    opened = script.index("Start-Process $url", start)
    assert script.index("Test-Station $Port", start) < opened, "wait for the station before opening the browser"
    assert "-NoNewWindow" in script, "the station lives in the launcher's own window"
    assert "$proc.WaitForExit()" in script, "the window stays as the station's while it runs"


def test_the_script_starts_the_installed_ollama_and_never_blocks_on_it():
    script = SCRIPT.read_text(encoding="ascii")
    assert 'Programs\Ollama\ollama app.exe' in script
    assert '"--hide", "--fast-startup"' in script, "the tray app must not open its chat window on top of the demo"
    assert "sans assistant" in script, "without Ollama the station still starts and the page says so"


def test_an_already_running_station_just_gets_a_browser():
    script = SCRIPT.read_text(encoding="ascii")
    first = script.index("Test-Station $Port")
    assert "Start-Process $url" in script[first:first + 400]
    assert "exit 0" in script[first:first + 400]
