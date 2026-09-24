"""Loads config.toml once, at import, and exposes it as plain objects."""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - Python 3.10 and older
    raise SystemExit(
        "MedBox needs Python 3.11 or newer (it uses the standard-library TOML reader).\n"
        f"You are running {sys.version.split()[0]}. Run setup.py, which checks this for you."
    )

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.toml"
VENV = ROOT / ".venv"


def python_command(script: str) -> str:
    """The command a person should actually type to run one of our scripts.

    Every dependency lives in .venv, so a bare `python tools/assets.py` runs
    an interpreter that cannot see faster-whisper and reports it as missing.
    The person then installs it with the wrong pip, into the wrong place, and
    the server still says it is not there. Telling somebody to run a command
    that cannot work is worse than telling them nothing, so any message that
    names a command builds it here.

    The same string is spelled out independently in tools/assets.py, which
    stays free of project imports on purpose. A test asserts the two agree.
    """
    if sys.platform.startswith("win"):
        # The leading .\ is not decoration. PowerShell refuses to run a
        # relative path without it — "the term .venv\Scripts\python is not
        # recognized" — and it tries to load anything starting with a bare dot
        # as a module, so the error it gives does not even mention paths.
        return f".\\.venv\\Scripts\\python {script.replace('/', chr(92))}"
    return f".venv/bin/python {script}"


@dataclass(frozen=True)
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 8080
    board_hz: int = 10
    sample_hz: int = 20


@dataclass(frozen=True)
class AIConfig:
    required_ollama: str = "0.13.1"
    host: str = "http://127.0.0.1:11434"
    model: str = "qwen2.5:1.5b-instruct"
    fallback_models: tuple[str, ...] = ()
    timeout_seconds: float = 20.0
    # A typed or spoken question: past this the station answers itself.
    # Eddy, 24 Sep: three to five seconds, after that it is too long.
    answer_timeout_seconds: float = 10.0
    # The model that answers typed and spoken questions; empty means the
    # assessment model. A 0.5B model answers in about three seconds where
    # the 1.5B takes eight on the defence laptop (24 Sep).
    answer_model: str = ""
    # Loading the model from disk is a different operation from answering a
    # warm request.  Keep its longer ceiling separate so a cold start cannot
    # weaken the normal slow-track timeout.
    warmup_timeout_seconds: float = 90.0
    # Zero: the schema already guarantees valid JSON, so randomness buys
    # variance and nothing else, and a demo you can rehearse is worth more.
    temperature: float = 0.0
    # How long Ollama holds the weights in memory after a question.
    keep_alive: str = "2h"
    # CPU threads for generation. 0 lets Ollama choose, which on a laptop with
    # performance and efficiency cores is not the fastest choice.
    num_thread: int = 0


@dataclass(frozen=True)
class DatabaseConfig:
    path: str = "data/medbox.db"

    @property
    def resolved(self) -> Path:
        p = Path(self.path)
        return p if p.is_absolute() else ROOT / p


@dataclass(frozen=True)
class ShipConfig:
    name: str = "ESA Horizon"
    crew_size: int = 40
    quarantine_zones: tuple[str, ...] = ("A", "B", "C")
    zone_capacity: int = 8


@dataclass(frozen=True)
class Config:
    server: ServerConfig = field(default_factory=ServerConfig)
    ai: AIConfig = field(default_factory=AIConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    ship: ShipConfig = field(default_factory=ShipConfig)


def load(path: Path | None = None) -> Config:
    path = path or CONFIG_PATH
    if not path.exists():
        return Config()
    raw = tomllib.loads(path.read_text(encoding="utf-8"))

    # The portable launcher chooses ports and writable storage at runtime.
    # Environment overrides let it do that without rewriting the signed or
    # hashed configuration inside the bundle.
    server_raw = dict(raw.get("server", {}))
    ai_raw = dict(raw.get("ai", {}))
    database_raw = dict(raw.get("database", {}))
    if os.environ.get("MEDBOX_PORT"):
        server_raw["port"] = int(os.environ["MEDBOX_PORT"])
    if os.environ.get("MEDBOX_OLLAMA_HOST"):
        ai_raw["host"] = os.environ["MEDBOX_OLLAMA_HOST"]
    if os.environ.get("MEDBOX_DATABASE"):
        database_raw["path"] = os.environ["MEDBOX_DATABASE"]
    return Config(
        server=ServerConfig(**server_raw),
        ai=AIConfig(
            **{
                **ai_raw,
                "fallback_models": tuple(ai_raw.get("fallback_models", [])),
            }
        ),
        database=DatabaseConfig(**database_raw),
        ship=ShipConfig(
            **{
                **raw.get("ship", {}),
                "quarantine_zones": tuple(
                    raw.get("ship", {}).get("quarantine_zones", ["A", "B", "C"])
                ),
            }
        ),
    )


CONFIG = load()
