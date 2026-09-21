"""setup.py must not report a setup that did not happen as a success.

On Windows, Ollama ships as an installer: setup downloads it, launches it, and
a person has to finish it. That is neither a failure nor a warning — nothing is
wrong, and nothing is finished either. Reported as a warning it produced
"Ready, with 1 warning(s)." and exit 0 on a machine with no Ollama and no
model, and the warnings were only counted, never shown. Somebody would read
"Ready", start the station, and find it had no assistant.

This project's whole claim is that it tells you what it actually knows. A setup
script that says Ready when it is not is the same failure as an assistant that
invents a diagnosis, in a place nobody thinks to look.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _setup():
    """Import setup.py by path; it is a script, not a package module."""
    spec = importlib.util.spec_from_file_location("medbox_setup", ROOT / "setup.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_an_unfinished_step_is_not_reported_as_ready(capsys):
    s = _setup()
    s.unfinished.append("Ollama installer launched. Finish it, then run setup again.")
    s.sys.argv = ["setup.py", "--check"]
    code = s.main()
    out = capsys.readouterr().out
    assert code != 0, "setup exited 0 with a step still unfinished"
    assert "NOT finished" in out
    assert "Ollama installer launched" in out, "the unfinished step is not named"
    assert "Ready" not in out.split("NOT finished")[-1], "it still claims to be ready"


def test_warnings_are_listed_and_not_merely_counted(capsys):
    """A count says something is wrong and not what, which is the least useful
    message available."""
    s = _setup()
    s.warnings.append("Ollama not found")
    s.sys.argv = ["setup.py", "--check"]
    s.main()
    out = capsys.readouterr().out
    assert "Ollama not found" in out, "warnings are counted but never shown"


def test_the_fallback_model_comes_from_config_not_from_this_file():
    """It was hardcoded to llama3.2:3b, which config.toml does not list and
    which is not Apache-2.0 — the licence question the model choice was
    settled on in the first place."""
    s = _setup()
    fallbacks = s.read_fallback_models()
    assert fallbacks, "config.toml declares no fallback_models"
    src = (ROOT / "setup.py").read_text(encoding="utf-8")
    body = "\n".join(ln for ln in src.splitlines() if not ln.strip().startswith("#"))
    assert "llama3.2" not in body, (
        "setup.py still names a model config.toml does not declare"
    )
    for tag in fallbacks:
        assert tag.startswith("qwen"), (
            f"fallback {tag} is outside the family the probe matches on"
        )


def test_the_installer_download_is_staged_and_has_a_timeout():
    """urlretrieve takes no timeout and writes straight to the final name, so a
    stalled campus network hangs forever and an interruption leaves a truncated
    OllamaSetup.exe that the next run would launch."""
    src = (ROOT / "setup.py").read_text(encoding="utf-8")
    body = "\n".join(ln for ln in src.splitlines() if not ln.strip().startswith("#"))
    assert "urlretrieve" not in body, "the installer download has no timeout"
    assert "timeout=" in body, "no timeout on the installer download"
    assert ".exe.part" in body, "the installer is not staged"


def test_the_daemon_being_down_is_not_read_as_having_no_models():
    """Finding ollama.exe is not the same as the daemon running. `ollama list`
    then fails, an empty stdout reads as an empty set, and setup attempts a
    pull that cannot work and blames the model for it."""
    src = (ROOT / "setup.py").read_text(encoding="utf-8")
    assert "tags.returncode" in src, (
        "installed_tags() ignores whether `ollama list` actually worked"
    )
    assert "not answering" in src or "not running" in src, (
        "nothing tells the user the daemon is down"
    )
