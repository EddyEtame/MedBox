#!/usr/bin/env python3
"""MedBox one-command setup. Works identically on Windows and Linux.

    python setup.py              full setup
    python setup.py --no-ollama  skip everything AI (useful offline)
    python setup.py --check      report what is installed, change nothing

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


def ok(msg: str) -> None:
    print(f"  {GREEN}OK{RESET}    {msg}")


def warn(msg: str) -> None:
    print(f"  {YELLOW}WARN{RESET}  {msg}")
    warnings.append(msg)


def fail(msg: str) -> None:
    print(f"  {RED}FAIL{RESET}  {msg}")
    failures.append(msg)


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


# --------------------------------------------------------------------------
def check_python() -> bool:
    step("1. Python")
    v = sys.version_info
    if (v.major, v.minor) < MIN_PYTHON:
        fail(
            f"Python {v.major}.{v.minor} found, {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ needed. "
            f"Install it from python.org and re-run."
        )
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


def install_ollama(assume_yes: bool, required: str = "") -> str | None:
    """Install Ollama, pinned to `required` when we know which version to want."""
    if IS_WINDOWS:
        url = OLLAMA_WINDOWS_PINNED.format(v=required) if required else OLLAMA_WINDOWS_LATEST
        warn("Ollama is not installed.")
        print(f"        Download and run: {url}")
        if required:
            print(f"        (pinned to {required} so both machines match)")
        if not assume_yes:
            answer = input("        Download the installer now and launch it? [y/N] ").strip().lower()
            if answer != "y":
                print(f"        Skipped. Install it yourself from {OLLAMA_DOWNLOAD_PAGE}, then re-run setup.")
                return None
        target = ROOT / "OllamaSetup.exe"
        try:
            # The size is printed from the response, not guessed. This said
            # "about 200 MB" for a long time and the pinned installer is
            # 1.22 GB, so somebody on a school network watched a silent
            # progress-free download run six times longer than promised, which
            # is indistinguishable from a hang.
            def progress(block: int, size: int, total: int) -> None:
                if total <= 0:
                    return
                done = min(block * size, total)
                print(f"\r        {done / 1e6:>7.0f} / {total / 1e6:.0f} MB",
                      end="", flush=True)

            print("        Downloading the Ollama installer. This is over a")
            print("        gigabyte, so give it a few minutes.")
            urllib.request.urlretrieve(url, target, reporthook=progress)
            print()
        except (urllib.error.URLError, OSError) as exc:
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
        print("        Launching the installer. Finish it, then re-run this script.")
        try:
            os.startfile(str(target))  # type: ignore[attr-defined]
        except Exception:
            print(f"        Run it yourself: {target}")
        return None

    # Linux / macOS. The official script installs whatever is current unless
    # OLLAMA_VERSION says otherwise, and "whatever is current" is exactly the
    # drift we are trying to avoid between two developers.
    warn("Ollama is not installed.")
    if not assume_yes:
        answer = input(f"        Run the official installer from {OLLAMA_LINUX_INSTALL}? [y/N] ").strip().lower()
        if answer != "y":
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

    def installed_tags() -> set[str]:
        tags = run([binary, "list"])
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
    if model in pulled or f"{model}:latest" in pulled:
        ok(f"model {model} already pulled")
        report(pulled)
        return True

    print(f"        Pulling {model}. First time this downloads about 1 GB.")
    r = subprocess.run([binary, "pull", model])
    if r.returncode != 0:
        warn(
            f"Could not pull {model}. Try a fallback from config.toml, e.g.\n"
            f"        ollama pull llama3.2:3b     then set it as `model` in config.toml"
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
    if check_only or not venv_python().exists():
        warn("skipped")
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

    if warnings:
        print(f"{YELLOW}Ready, with {len(warnings)} warning(s).{RESET}")
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
