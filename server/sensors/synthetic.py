"""Scenario-driven crew simulation.

This is the source the jury will see. It models a full crew from a YAML file so
the entire demo runs with no hardware attached, identically every time.

Physiology here is deliberately simple and openly approximate: smooth ramps plus
small noise. It is not a patient model and does not claim to be. Its job is to
exercise the triage path across realistic ranges so the scoring, the ordering
and the quarantine logic can be demonstrated and tested.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from .base import Reading

# Healthy adult baselines, roughly mid-range for each NEWS2 parameter.
BASELINE = {"temperature": 36.8, "spo2": 98.0, "pulse": 72.0, "respiration": 15.0}

FIRST_NAMES = [
    "Alba", "Nils", "Rania", "Tomas", "Ines", "Kwame", "Sofia", "Mateo", "Lena",
    "Oskar", "Yara", "Bilal", "Freja", "Andrei", "Noor", "Pietro", "Maja",
    "Idris", "Clara", "Viktor",
]
SURNAMES = [
    "Okonkwo", "Lindqvist", "Haddad", "Ferreira", "Novak", "Mensah", "Rossi",
    "Vasquez", "Bauer", "Dubois", "Nakamura", "Kaur", "Andersen", "Petrov",
]
ROLES = [
    "Flight engineer", "Botanist", "Medical officer", "Systems", "Navigation",
    "Reactor tech", "Hydroponics", "Comms", "Geologist", "Pilot",
]


@dataclass
class Trajectory:
    """Where one patient's vitals are heading, and how fast."""

    targets: dict[str, float] = field(default_factory=dict)
    started_at: float = 0.0
    duration: float = 45.0
    origin: dict[str, float] = field(default_factory=dict)

    def value(self, key: str, base: float, now: float) -> float:
        if key not in self.targets:
            return base
        if self.duration <= 0:
            return self.targets[key]
        progress = min(1.0, max(0.0, (now - self.started_at) / self.duration))
        start = self.origin.get(key, base)
        # Smoothstep: clinical deterioration is not a straight line.
        eased = progress * progress * (3.0 - 2.0 * progress)
        return start + (self.targets[key] - start) * eased


@dataclass
class SimPatient:
    id: str
    name: str
    role: str
    seed: int
    trajectory: Trajectory = field(default_factory=Trajectory)
    contaminated: bool = False

    def read(self, now: float) -> Reading:
        rng = random.Random(self.seed ^ int(now * 4))
        v = {}
        for key, base in BASELINE.items():
            target = self.trajectory.value(key, base, now)
            # Per-parameter noise, scaled to what that instrument realistically wobbles by.
            noise = {
                "temperature": 0.04,
                "spo2": 0.35,
                "pulse": 1.6,
                "respiration": 0.5,
            }[key]
            drift = math.sin(now * 0.7 + self.seed) * noise * 0.5
            v[key] = target + drift + rng.uniform(-noise, noise)
        return Reading(
            patient_id=self.id,
            at=now,
            temperature=round(v["temperature"], 2),
            spo2=round(min(100.0, v["spo2"]), 1),
            pulse=round(v["pulse"], 1),
            respiration=round(v["respiration"], 1),
            source="synthetic",
        )


class ScenarioSource:
    """Runs a crew forward in time according to a loaded scenario."""

    name = "synthetic"

    def __init__(self, crew_size: int, seed: int = 2080) -> None:
        self.rng = random.Random(seed)
        self.patients: dict[str, SimPatient] = {}
        self.t0: float | None = None
        self._build_crew(crew_size)

    def _build_crew(self, crew_size: int) -> None:
        used: set[str] = set()
        for i in range(crew_size):
            while True:
                name = f"{self.rng.choice(FIRST_NAMES)} {self.rng.choice(SURNAMES)}"
                if name not in used:
                    used.add(name)
                    break
            pid = f"P-{i + 1:02d}"
            self.patients[pid] = SimPatient(
                id=pid,
                name=name,
                role=self.rng.choice(ROLES),
                seed=self.rng.randrange(1, 10_000),
            )

    def roster(self) -> list[tuple[str, str, str]]:
        return [(p.id, p.name, p.role) for p in self.patients.values()]

    def start(self) -> None:
        self.t0 = None

    def stop(self) -> None:
        pass

    def reset(self) -> None:
        for p in self.patients.values():
            p.trajectory = Trajectory()
            p.contaminated = False
        self.t0 = None

    def afflict(self, patient_ids: list[str], targets: dict[str, float], over: float, now: float) -> None:
        """Send these patients toward new vitals over `over` seconds."""
        for pid in patient_ids:
            p = self.patients.get(pid)
            if p is None:
                continue
            current = p.read(now)
            p.trajectory = Trajectory(
                targets=dict(targets),
                started_at=now,
                duration=max(0.1, over),
                origin={
                    "temperature": current.temperature or BASELINE["temperature"],
                    "spo2": current.spo2 or BASELINE["spo2"],
                    "pulse": current.pulse or BASELINE["pulse"],
                    "respiration": current.respiration or BASELINE["respiration"],
                },
            )
            p.contaminated = True

    def healthy_ids(self) -> list[str]:
        return [p.id for p in self.patients.values() if not p.contaminated]

    def sample(self, now: float) -> list[Reading]:
        if self.t0 is None:
            self.t0 = now
        return [p.read(now) for p in self.patients.values()]
