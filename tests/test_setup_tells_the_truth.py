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


# --------------------------------------------------------------------------
# The Ollama step asks before it downloads 1.2 GB. Asking is right; asking
# where nobody can answer is how setup hangs with a blank screen.
class FakeStream:
    def __init__(self, tty: bool, answer: str = "") -> None:
        self._tty, self._answer = tty, answer

    def isatty(self) -> bool:
        return self._tty

    def readline(self) -> str:
        return self._answer

    def write(self, _text: str) -> int:
        return 0

    def flush(self) -> None:
        pass


def use_streams(monkeypatch, stdin, stdout):
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys, "stdout", stdout)


def test_yes_up_front_never_asks(monkeypatch):
    """-y is the answer for a machine with nobody at it."""
    setup = _setup()
    use_streams(monkeypatch, FakeStream(False), FakeStream(False))
    assert setup.confirm("would never be answerable? ", True) is True


def test_a_redirected_screen_is_never_asked(monkeypatch):
    """`setup.ps1 *> setup.log` — the obvious thing to do when somebody asks
    you for the full output. CPython writes an input() prompt to the console
    only when stdin AND stdout are a tty; with stdout redirected the prompt
    goes into the file and the read blocks on a console showing nothing. It is
    indistinguishable from a hung 1.2 GB download, and there is no timeout.

    Measured before this was written: a pty on stdin and a file on stdout, and
    the terminal received the empty string while the prompt sat in the file.
    """
    setup = _setup()
    use_streams(monkeypatch, FakeStream(True, "y\n"), FakeStream(False))
    assert setup.confirm("must not be asked? ", False) is False


def test_no_terminal_at_all_declines_rather_than_crashing(monkeypatch):
    """Task Scheduler, `< NUL`, an IDE's run button, another program driving
    this. input() raised EOFError, which nothing caught, so setup died with a
    traceback halfway through step 3 and never created the database or ran the
    tests."""
    setup = _setup()

    class NoInput(FakeStream):
        def readline(self):
            raise EOFError

    use_streams(monkeypatch, NoInput(False), FakeStream(False))
    assert setup.confirm("nobody is there? ", False) is False


def test_it_declines_rather_than_helping_itself(monkeypatch):
    """Downloading 1.2 GB, or piping a remote script into sh, because nobody
    was watching is not a favour. Silence is No; -y is Yes."""
    setup = _setup()
    use_streams(monkeypatch, FakeStream(False), FakeStream(False))
    assert setup.confirm("start a big download? ", False) is False


def test_typing_the_whole_word_yes_works(monkeypatch):
    """A [y/N] prompt that silently declines when somebody types "yes" is the
    worst answer available: it looks like it worked and it did nothing."""
    setup = _setup()
    monkeypatch.setattr("builtins.input", lambda _prompt="": "  YES  ")
    use_streams(monkeypatch, FakeStream(True), FakeStream(True))
    assert setup.confirm("well? ", False) is True

    monkeypatch.setattr("builtins.input", lambda _prompt="": "n")
    assert setup.confirm("well? ", False) is False


def test_the_flag_that_answers_the_prompt_is_documented():
    """It existed and appeared in no usage text anywhere, so the only way past
    the prompt was undiscoverable."""
    doc = (ROOT / "setup.py").read_text(encoding="utf-8").split('"""')[1]
    assert "-y" in doc, "setup.py's own usage block never mentions -y"
    for path in ("README.md", "setup.ps1"):
        text = (ROOT / path).read_text(encoding="utf-8")
        assert "-y" in text, f"{path} never mentions -y"
