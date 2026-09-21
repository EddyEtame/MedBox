#!/usr/bin/env python3
"""MedBox one-command setup. Works identically on Windows and Linux.

    python setup.py              full setup
    python setup.py --no-ollama  skip everything AI (useful offline)
    python setup.py --check      report what is installed, change nothing
    python setup.py -y           answer yes to the install prompts (unattended)

It creates the virtual environment, installs pinned dependencies, installs and
version-checks Ollama, pulls the model, creates the database and runs the tests.
Safe to run repeatedly: every step checks before it acts.

Written with the standard library only, so it runs before anything is installed.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
IS_WINDOWS = platform.system() == "Windows"
MIN_PYTHON = (3, 11)

OLLAMA_LINUX_INSTALL = "https://ollama.com/install.sh"
OLLAMA_DOWNLOAD_PAGE = "https://ollama.com/download"
# Pinning matters more than convenience here: two developers who install on
# two different days must end up on the SAME Ollama, or a bug on one machine
# is unreproducible on the other. The official install script honours
# OLLAMA_VERSION, and every release has a Windows installer at a stable URL.
OLLAMA_WINDOWS_PINNED = "https://github.com/ollama/ollama/releases/download/v{v}/OllamaSetup.exe"
OLLAMA_WINDOWS_LATEST = "https://ollama.com/download/OllamaSetup.exe"

GREEN, YELLOW, RED, DIM, RESET = "\033[32m", "\033[33m", "\033[31m", "\033[2m", "\033[0m"
if IS_WINDOWS and not os.environ.get("WT_SESSION"):
    GREEN = YELLOW = RED = DIM = RESET = ""

failures: list[str] = []
warnings: list[str] = []
# A third outcome, because two were not enough. Launching an installer and
# waiting for a human is neither a failure nor a warning: nothing is wrong, and
# nothing is finished either. Reported as a warning it became "Ready, with 1
# warning(s)." and exit 0 on a machine with no Ollama and no model — the
# station would start and simply have no assistant, which is the quiet kind of
# lie this project is built to avoid.
unfinished: list[str] = []


def ok(msg: str) -> None:
    print(f"  {GREEN}OK{RESET}    {msg}")


def warn(msg: str) -> None:
    print(f"  {YELLOW}WARN{RESET}  {msg}")
    warnings.append(msg)


def fail(msg: str) -> None:
    print(f"  {RED}FAIL{RESET}  {msg}")
    failures.append(msg)


def pending(msg: str) -> None:
    """Something was started that a person has to finish."""
    print(f"  {YELLOW}WAIT{RESET}  {msg}")
    unfinished.append(msg)


def step(title: str) -> None:
    print(f"\n{title}")
    print(DIM + "-" * max(12, len(title)) + RESET)


def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if IS_WINDOWS else "bin/python")


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def read_required_ollama() -> str:
    """Read the pinned version out of config.toml without needing a TOML parser."""
    cfg = ROOT / "config.toml"
    if not cfg.exists():
        return ""
    for line in cfg.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("required_ollama"):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


VERSION_RE = re.compile(r"(\d+\.\d+\.\d+)")


def parse_ollama_version(text: str) -> str:
    """`ollama --version` may also print a warning about the daemon not
    running, so take the first thing shaped like a version rather than the
    last token of the combined output."""
    m = VERSION_RE.search(text or "")
    return m.group(1) if m else "unknown"


def read_model() -> str:
    cfg = ROOT / "config.toml"
    if not cfg.exists():
        return "qwen2.5:3b-instruct"
    for line in cfg.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s.startswith("model") and "=" in s:
            return s.split("=", 1)[1].strip().strip('"').strip("'")
    return "qwen2.5:3b-instruct"


def read_fallback_models() -> list[str]:
    """`fallback_models` from config.toml, same hand-rolled read as read_model."""
    try:
        text = (ROOT / "config.toml").read_text(encoding="utf-8")
    except OSError:
        return []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("fallback_models") and "=" in s:
            inside = s.split("=", 1)[1].strip().strip("[]")
            return [p.strip().strip('"').strip("'") for p in inside.split(",") if p.strip()]
    return []


# --------------------------------------------------------------------------
def check_python() -> bool:
    step("1. Python")
    v = sys.version_info
    if (v.major, v.minor) < MIN_PYTHON:
        fail(
            f"Python {v.major}.{v.minor} found, {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ needed."
        )
        # WHICH one, always. A machine can carry several Pythons and the
        # launcher can hand over the oldest: `py -3` resolved to 3.9.13 here
        # while a working 3.11.9 sat on PATH as `python`, and the message
        # without this line reads as "go and install Python" to somebody who
        # already has it. setup.ps1 now probes the version rather than
        # trusting the launcher; this line is how you see which one answered.
        print(f"        {sys.executable}")
        print("        Install it from https://www.python.org/downloads/ and re-run.")
        return False
    # The path, not just the number. When a wheel fails to build later, the
    # first question is always which interpreter ran, and on Windows `py -3`
    # may have picked a different one than the person expected.
    ok(f"Python {v.major}.{v.minor}.{v.micro} on {platform.system()}")
    print(f"        {sys.executable}")
    return True


def setup_venv(check_only: bool) -> bool:
    step("2. Virtual environment and dependencies")
    if check_only:
        (ok if venv_python().exists() else warn)(
            f".venv {'present' if venv_python().exists() else 'not created yet'}"
        )
        return venv_python().exists()

    if not venv_python().exists():
        r = run([sys.executable, "-m", "venv", str(VENV)])
        if r.returncode != 0:
            fail(f"Could not create .venv: {r.stderr.strip()[:300]}")
            return False
        ok("created .venv")
    else:
        ok(".venv already present")

    py = str(venv_python())
    run([py, "-m", "pip", "install", "--upgrade", "pip", "-q"])
    r = run([py, "-m", "pip", "install", "-q", "-r", str(ROOT / "requirements.txt")])
    if r.returncode != 0:
        fail(f"pip install failed: {r.stderr.strip()[:400]}")
        return False
    ok("dependencies installed from requirements.txt")

    # Speech-in, and it is allowed to fail. These are prebuilt wheels carrying
    # compiled extensions, so they are the likeliest line in this whole script
    # to fall over on somebody's machine, and a laptop that cannot run the
    # demo because an optional microphone would not install is a far worse
    # outcome than a laptop with no microphone. Without them the button is
    # hidden and typing works.
    speech = ROOT / "requirements-speech.txt"
    if speech.exists():
        r = run([py, "-m", "pip", "install", "-q", "-r", str(speech)])
        if r.returncode == 0:
            ok("speech dependencies installed (hold-to-speak available)")
        else:
            why = r.stderr.strip().splitlines()[-1][:160] if r.stderr.strip() else ""
            warn("speech dependencies would not install, so the microphone "
                 "stays hidden and typing still works"
                 + (f" ({why})" if why else ""))
    return True


def ollama_binary() -> str | None:
    found = shutil.which("ollama")
    if found:
        return found
    if IS_WINDOWS:
        # Ollama's Windows installer is per-user and does not always update PATH
        # in the current shell, so look where it actually lands.
        guess = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Ollama/ollama.exe"
        if guess.exists():
            return str(guess)
    return None


def confirm(prompt: str, assume_yes: bool) -> bool:
    """Ask a yes/no question, or answer it ourselves when nobody can be asked.

    `-y` wins first: that is the whole point of the flag.

    Then a tty test that checks stdout as well as stdin, and not stdin alone.
    CPython only writes an input() prompt to the console when BOTH are a tty.
    With just stdout redirected — `... *> setup.log`, `| Tee-Object`, the
    obvious thing to do after a screen of errors when somebody asks you for
    the full output — the prompt is written into the file and the read blocks
    on a console showing nothing at all. Measured, not reasoned about: with a
    pty on stdin and a file on stdout, the terminal received the empty string
    and the prompt was sitting in the file. Checking stdin alone walks
    straight into that, and it is indistinguishable from a hung download.

    With no console stdin at all — Task Scheduler, `< NUL`, an IDE run button,
    another program driving this — input() raises EOFError, which nothing
    caught. setup died with a traceback in the middle of step 3, so the
    database was never created and the tests never ran.

    It declines rather than proceeds. Starting a 1.2 GB download, or piping a
    remote script into sh, because nobody was watching is not an improvement.
    `-y` is how you say yes when nobody is there to be asked.

    sys.stdin and sys.stdout are None under pythonw.exe and .isatty() raises
    on a closed stream, so neither is dereferenced without a guard.
    """
    if assume_yes:
        return True
    try:
        interactive = (
            sys.stdin is not None
            and sys.stdout is not None
            and sys.stdin.isatty()
            and sys.stdout.isatty()
        )
    except (ValueError, OSError):
        interactive = False
    if not interactive:
        print("        Nothing was downloaded: this is not an interactive terminal,")
        print("        so there is no way to ask. Run it in a PowerShell window, or")
        print("        pass -y to answer yes up front.")
        return False
    try:
        # "yes" as well as "y". A [y/N] prompt that silently declines when
        # somebody types the whole word is the worst answer available.
        return input(prompt).strip().lower() in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        print()
        return False


def install_ollama(assume_yes: bool, required: str = "") -> str | None:
    """Install Ollama, pinned to `required` when we know which version to want."""
    if IS_WINDOWS:
        url = OLLAMA_WINDOWS_PINNED.format(v=required) if required else OLLAMA_WINDOWS_LATEST
        warn("Ollama is not installed.")
        print(f"        Download and run: {url}")
        if required:
            print(f"        (pinned to {required} so both machines match)")
        if not confirm("        Download the installer now and launch it? [y/N] ", assume_yes):
            print(f"        Skipped. Install it yourself from {OLLAMA_DOWNLOAD_PAGE}, then re-run setup.")
            return None
        target = ROOT / "OllamaSetup.exe"
        staging = target.with_suffix(".exe.part")
        try:
            # Not urlretrieve. It takes no timeout, and nothing here sets a
            # default one, so a stalled connection on the campus network this
            # whole branch is worrying about hangs forever with the byte
            # counter frozen — which looks exactly like a slow 1.2 GB
            # transfer. It also writes straight to the final name, so an
            # interruption leaves a truncated OllamaSetup.exe that the next run
            # would happily launch.
            #
            # The size is read from the response rather than guessed. This said
            # "about 200 MB" for a long time and the pinned installer is
            # 1.22 GB, so somebody watched a silent download run six times
            # longer than promised, which is indistinguishable from a hang.
            print("        Downloading the Ollama installer.")
            with urllib.request.urlopen(url, timeout=60) as r:
                total = int(r.headers.get("Content-Length") or 0)
                if total:
                    print(f"        {total / 1e9:.2f} GB, so give it a few minutes.")
                seen = 0
                with staging.open("wb") as out:
                    while True:
                        chunk = r.read(1 << 20)
                        if not chunk:
                            break
                        out.write(chunk)
                        seen += len(chunk)
                        if total:
                            print(f"\r        {seen / 1e6:>7.0f} / {total / 1e6:.0f} MB",
                                  end="", flush=True)
            if total:
                print()
            if total and seen < total:
                raise OSError(f"download stopped early at {seen} of {total} bytes")
            staging.replace(target)
        except (urllib.error.URLError, OSError) as exc:
            # A truncated installer is worse than none, because the next run
            # would launch it.
            staging.unlink(missing_ok=True)
            if required:
                # The pinned release may not carry that asset name. Say so
                # plainly rather than silently installing a different version.
                fail(
                    f"Could not download the pinned Ollama {required}: {exc}\n"
                    f"        Check the version in config.toml against {OLLAMA_DOWNLOAD_PAGE}"
                )
            else:
                fail(f"Download failed: {exc}. Install manually from {OLLAMA_DOWNLOAD_PAGE}")
            return None
        try:
            os.startfile(str(target))  # type: ignore[attr-defined]
            pending("Ollama installer launched. Finish it, then run setup again.")
        except Exception:
            pending(f"Run the installer yourself: {target}, then run setup again.")
        return None

    # Linux / macOS. The official script installs whatever is current unless
    # OLLAMA_VERSION says otherwise, and "whatever is current" is exactly the
    # drift we are trying to avoid between two developers.
    warn("Ollama is not installed.")
    if not confirm(f"        Run the official installer from {OLLAMA_LINUX_INSTALL}? [y/N] ", assume_yes):
        print("        Skipped. Install it yourself, then re-run setup.")
        return None
    env = dict(os.environ)
    if required:
        env["OLLAMA_VERSION"] = required
        print(f"        Installing Ollama {required} (pinned in config.toml)")
    r = subprocess.run(f"curl -fsSL {OLLAMA_LINUX_INSTALL} | sh", shell=True, env=env)
    if r.returncode != 0:
        fail("The Ollama installer failed. Install it manually and re-run setup.")
        return None
    return ollama_binary()


def setup_ollama(check_only: bool, assume_yes: bool) -> bool:
    step("3. Ollama")
    required = read_required_ollama()
    binary = ollama_binary()

    if binary is None:
        if check_only:
            warn("Ollama not found")
            return False
        binary = install_ollama(assume_yes, required)
        if binary is None:
            return False

    r = run([binary, "--version"])
    version = parse_ollama_version(r.stdout + r.stderr) if r.returncode == 0 else "unknown"
    if required and version != required:
        # A mismatch is a warning, not a stop: it usually still works, but both
        # machines and the demo laptop should be identical before Friday.
        warn(
            f"Ollama {version} installed, config.toml pins {required}.\n"
            f"        Both machines and the demo laptop should be on {required} before Friday.\n"
            f"        Linux:   curl -fsSL {OLLAMA_LINUX_INSTALL} | OLLAMA_VERSION={required} sh\n"
            f"        Windows: {OLLAMA_WINDOWS_PINNED.format(v=required)}"
        )
    else:
        ok(f"Ollama {version}")

    if check_only:
        return True

    model = read_model()

    def installed_tags() -> set[str] | None:
        """The tags Ollama holds, or None if it could not be asked.

        None and "no models" are different answers and were being conflated.
        Finding ollama.exe is not the same as the daemon running — on Windows
        the binary is found via %LOCALAPPDATA% while the tray app that actually
        serves the API may be stopped. `ollama list` then fails, an empty
        stdout read as an empty set, and setup went on to attempt a pull that
        could not work and blamed the model for it.
        """
        tags = run([binary, "list"])
        if tags.returncode != 0:
            return None
        return {ln.split()[0] for ln in tags.stdout.splitlines()[1:] if ln.strip()}

    def report(pulled: set[str]) -> None:
        """Print the tags Ollama actually holds, not the one we asked for.

        server/ai/ollama.py matches the configured model against this list by
        name, and a tag that differs by so much as a suffix makes the probe
        decide the model is not there — at which point the stand-in answers and
        says so, quietly, instead of the real model. Printing what Ollama
        really reports is how a mismatch gets noticed here rather than on
        stage.
        """
        if pulled:
            print(f"        ollama list: {', '.join(sorted(pulled))}")

    pulled = installed_tags()
    if pulled is None:
        warn(
            "Ollama is installed but not answering, so it is probably not "
            "running.\n"
            "        Start the Ollama app (or run `ollama serve`), then run "
            "setup again."
        )
        return False
    if model in pulled or f"{model}:latest" in pulled:
        ok(f"model {model} already pulled")
        report(pulled)
        return True

    print(f"        Pulling {model}. First time this downloads about 1 GB.")
    r = subprocess.run([binary, "pull", model])
    if r.returncode != 0:
        # The resolved path, not the bare name. ollama_binary() exists
        # precisely because the Windows installer is per-user and does not
        # refresh the PATH of an already-open shell, so telling somebody to
        # type `ollama` here hands them the CommandNotFoundException that
        # brought them to this message in the first place.
        # The fallback comes from config.toml rather than a name written in
        # here. The hardcoded suggestion was llama3.2:3b, which config.toml
        # does not list and which is not Apache-2.0 — the licence question the
        # model choice was settled on in the first place.
        alt = read_fallback_models()
        suggestion = alt[0] if alt else model
        warn(
            f"Could not pull {model}. Try the fallback from config.toml:\n"
            f'        "{binary}" pull {suggestion}\n'
            f"        then set it as `model` in config.toml"
        )
        return False
    ok(f"pulled {model}")
    report(installed_tags())
    return True


def setup_database(check_only: bool) -> bool:
    step("4. Database")
    db_path = ROOT / "data" / "medbox.db"
    if check_only:
        (ok if db_path.exists() else warn)(
            f"database {'present' if db_path.exists() else 'not created yet'} ({db_path})"
        )
        return True
    py = str(venv_python()) if venv_python().exists() else sys.executable
    r = run(
        [py, "-c", "import sys; sys.path.insert(0,'.'); "
         "from server.config import CONFIG; from server.db import Database; "
         "d=Database(CONFIG.database.resolved); d.close(); print(CONFIG.database.resolved)"],
        cwd=str(ROOT),
    )
    if r.returncode != 0:
        fail(f"Could not create the database: {r.stderr.strip()[:400]}")
        return False
    ok(f"schema created at {r.stdout.strip()}")
    return True


def run_tests(check_only: bool) -> bool:
    step("5. Tests")
    # Each warning is now listed in the final verdict rather than counted, so
    # it has to say what was skipped and why on its own.
    if check_only:
        warn("tests not run (--check only reports)")
        return True
    if not venv_python().exists():
        warn("tests not run: there is no .venv yet")
        return True
    r = run([str(venv_python()), "-m", "pytest", "tests/", "-q"], cwd=str(ROOT))
    tail = (r.stdout or r.stderr).strip().splitlines()
    if r.returncode != 0:
        fail("tests failed:\n        " + "\n        ".join(tail[-8:]))
        return False
    ok(tail[-1] if tail else "passed")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description="Set up MedBox on this machine.")
    ap.add_argument("--check", action="store_true", help="report only, change nothing")
    ap.add_argument("--no-ollama", action="store_true", help="skip the AI entirely")
    ap.add_argument("-y", "--yes", action="store_true", help="answer yes to install prompts")
    args = ap.parse_args()

    print(f"\n{'MedBox setup':^58}")
    print(f"{'=' * 58}")
    print(f"{DIM}  {platform.system()} {platform.release()}  ·  {ROOT}{RESET}")

    if not check_python():
        print(f"\n{RED}Setup stopped.{RESET}\n")
        return 1

    setup_venv(args.check)
    if args.no_ollama:
        step("3. Ollama")
        warn("skipped (--no-ollama). MedBox runs without it; there is just no narration.")
    else:
        setup_ollama(args.check, args.yes)
    setup_database(args.check)
    run_tests(args.check)

    print(f"\n{'=' * 58}")
    if failures:
        print(f"{RED}{len(failures)} problem(s) to fix:{RESET}")
        for f in failures:
            print(f"  - {f}")
        return 1

    if unfinished:
        # Before the "Ready" paths, and non-zero, so the wrapper's exit code
        # says the same thing the screen does.
        print(f"{YELLOW}Setup is NOT finished.{RESET}")
        for u in unfinished:
            print(f"  - {u}")
        for w in warnings:
            print(f"  - {w}")
        print("\n  Finish the step above, then run setup again.")
        print("  Everything already done will be skipped.\n")
        return 2

    if warnings:
        print(f"{YELLOW}Ready, with {len(warnings)} warning(s):{RESET}")
        # Listed, not merely counted. A count tells somebody that something is
        # wrong and not what, which is the least useful possible message.
        for w in warnings:
            print(f"  - {w}")
    else:
        print(f"{GREEN}Ready.{RESET}")

    # The leading .\ is required on Windows: PowerShell will not run a command
    # from the current directory without a path qualifier, and because this one
    # starts with a dot it falls through to module auto-loading and reports
    # "The module '.venv' could not be loaded" — an error that never mentions
    # paths. This is the last line a successful setup prints, so getting it
    # wrong hands somebody a broken command at the exact moment they trust it.
    runner = (".\\.venv\\Scripts\\python medbox.py" if IS_WINDOWS
              else ".venv/bin/python medbox.py")
    print(f"\n  Start the station:   {runner}")
    print(f"  Then open:           http://127.0.0.1:8080\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
