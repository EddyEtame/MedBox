"""Scenario files: the demo, the test suite and the training set, all one format.

A scenario is a timeline of events applied to the synthetic crew. Running one
produces a recording; replaying a recording reproduces the run exactly. That is
what lets Friday's demo be the same one rehearsed on Wednesday.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .config import ROOT

SCENARIO_DIR = ROOT / "scenarios"


@dataclass
class Step:
    at: float
    action: str
    payload: dict[str, Any]


@dataclass
class Scenario:
    name: str
    description: str
    crew: int
    steps: list[Step]
    simulation: dict[str, Any] = field(default_factory=dict)

    @property
    def duration(self) -> float:
        declared = self.simulation.get("demo_duration")
        if declared is not None:
            return max(_parse_time(declared), max((s.at for s in self.steps), default=0.0))
        return max((s.at for s in self.steps), default=0.0) + 10.0


def _parse_time(value: Any) -> float:
    """Accept `12`, `12s`, `1m30s` or `1:30`."""
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if ":" in text:
        mins, _, secs = text.partition(":")
        return float(mins) * 60 + float(secs)
    total, number = 0.0, ""
    for ch in text:
        if ch.isdigit() or ch == ".":
            number += ch
        elif ch == "m":
            total += float(number or 0) * 60
            number = ""
        elif ch == "s":
            total += float(number or 0)
            number = ""
    return total + float(number or 0)


def load(name: str) -> Scenario:
    path = SCENARIO_DIR / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(
            f"No scenario named {name!r}. Available: {', '.join(available()) or 'none'}"
        )
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    steps = [
        Step(
            at=_parse_time(item.get("at", 0)),
            action=str(item.get("do", "noop")),
            payload={k: v for k, v in item.items() if k not in ("at", "do")},
        )
        for item in raw.get("timeline", [])
    ]
    steps.sort(key=lambda s: s.at)
    return Scenario(
        name=raw.get("name", name),
        description=raw.get("description", ""),
        crew=int(raw.get("crew", 40)),
        steps=steps,
        simulation=dict(raw.get("simulation", {})),
    )


def available() -> list[str]:
    if not SCENARIO_DIR.exists():
        return []
    return sorted(p.stem for p in SCENARIO_DIR.glob("*.yaml"))
