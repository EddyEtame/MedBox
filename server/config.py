"""Loads config.toml once, at import, and exposes it as plain objects."""
from __future__ import annotations

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


@dataclass(frozen=True)
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 8080
    board_hz: int = 10
    sample_hz: int = 20


@dataclass(frozen=True)
class AIConfig:
    required_ollama: str = "0.5.4"
    host: str = "http://127.0.0.1:11434"
    model: str = "qwen2.5:3b-instruct"
    fallback_models: tuple[str, ...] = ()
    timeout_seconds: float = 20.0
    temperature: float = 0.2


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
    return Config(
        server=ServerConfig(**raw.get("server", {})),
        ai=AIConfig(
            **{
                **raw.get("ai", {}),
                "fallback_models": tuple(raw.get("ai", {}).get("fallback_models", [])),
            }
        ),
        database=DatabaseConfig(**raw.get("database", {})),
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
