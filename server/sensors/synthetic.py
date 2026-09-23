"""Deterministic, evidence-anchored simulation for the MedBox demo.

The simulator never asks the language model for a number. Each crew member
starts from a stable personal healthy baseline. A scenario then applies
*changes from that baseline* and the sensor layer emits a time-correlated,
repeatable signal around the resulting trajectory.

This is a demonstration instrument, not a physiological twin and not a
diagnostic model. The provenance exposed by :meth:`ScenarioSource.metadata`
must travel with any graph or exported recording made from these readings.
"""
from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Mapping

from .base import Reading

VITALS = ("temperature", "spo2", "pulse", "respiration")

# Kept as a public compatibility constant. New patients receive a stable,
# patient-specific baseline inside the NEWS2 zero-score bands rather than this
# single shared midpoint.
BASELINE = {"temperature": 36.8, "spo2": 98.0, "pulse": 72.0, "respiration": 15.0}

# Conservative healthy demo ranges inside the NEWS2 zero-score ranges. These
# are not universal population reference intervals.
BASELINE_PROFILE_VERSION = "healthy-adult-reference-v1"
HEALTHY_BASELINE_RANGES = {
    "temperature": (36.5, 37.1),
    "spo2": (97.0, 99.0),
    "pulse": (60.0, 78.0),
    "respiration": (12.0, 17.0),
}

# Wobble is small enough that a healthy baseline cannot become an alarm merely
# because the simulated instrument moved by one sample.
NOISE_SCALE = {
    "temperature": 0.035,
    "spo2": 0.28,
    "pulse": 1.25,
    "respiration": 0.38,
}

# Each signal may react on its own schedule. This avoids the visibly artificial
# behaviour where temperature, pulse, breathing and oxygen all bend together.
DEFAULT_DELAYS = {
    "temperature": 0.0,
    "pulse": 2.0,
    "respiration": 3.0,
    "spo2": 8.0,
}
DEFAULT_DURATION_FACTORS = {
    "temperature": 1.00,
    "pulse": 0.72,
    "respiration": 0.78,
    "spo2": 1.00,
}

# Population-level associations reported by Jensen et al. in acutely admitted
# adults. They are used only when a scenario supplies a temperature change but
# omits pulse or respiration. They are plausibility anchors, not an individual
# causal law and never produce an SpO2 value.
TEMP_TO_PULSE_BPM_PER_C = 6.4
TEMP_TO_RESP_PER_MIN_PER_C = 1.2

PROVENANCE = {
    "model": "medbox-deterministic-simulation-v2",
    "label_fr": "DONNÉES SIMULÉES - HORLOGE ACCÉLÉRÉE - NON DIAGNOSTIQUE",
    "clock": {
        "mode": "accelerated",
        "simulated_minutes_per_real_second": 4.0,
        "note_fr": "90 secondes de démonstration représentent jusqu'à 6 heures de surveillance.",
    },
    "method": {
        "baseline": "deterministic selection inside healthy reference ranges; not an individual measurement",
        "trajectory": "x_v(t) = personal_baseline_v + operator_delta_v * smoothstep(t)",
        "residual": "seeded band-limited signal with a shared cross-vital component",
        "temperature_associations": "delta_pulse = 6.4 * delta_temperature; delta_respiration = 1.2 * delta_temperature when omitted",
        "noise_calibration": "demonstration parameters; not fitted to an individual or claimed as a clinical law",
    },
    "sources": [
        {
            "use": "deterministic-score-overlay-only",
            "title": "Royal College of Physicians NEWS2",
            "url": "https://www.rcp.ac.uk/improving-care/resources/national-early-warning-score-news-2",
        },
        {
            "use": "healthy-reference-ranges",
            "title": "MedlinePlus Vital Signs",
            "url": "https://medlineplus.gov/ency/article/002341.htm",
        },
        {
            "use": "healthy-spo2-reference",
            "title": "MedlinePlus Pulse Oximetry",
            "url": "https://medlineplus.gov/lab-tests/pulse-oximetry/",
        },
        {
            "use": "candidate-validation-dataset; no runtime fitting and no patient rows shipped",
            "title": "PhysioNet Computing in Cardiology Challenge 2019",
            "url": "https://physionet.org/content/challenge-2019/1.0.0/",
        },
        {
            "use": "temperature-pulse-respiration-population-association",
            "title": "Jensen et al. 2015, Crit Care",
            "url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC4511462/",
            "coefficients": {
                "pulse_bpm_per_c_adjusted": TEMP_TO_PULSE_BPM_PER_C,
                "respirations_per_min_per_c_adjusted": TEMP_TO_RESP_PER_MIN_PER_C,
            },
        },
    ],
    "limits_fr": [
        "Les valeurs sont synthétiques et ne représentent aucun patient réel.",
        "Une variation ou un score d'alerte n'est pas un diagnostic.",
        "La SpO2 n'est jamais déduite de la température.",
        "Les délais par défaut servent la chorégraphie de démonstration; ils ne décrivent pas un délai clinique universel.",
        "Aucun LLM ne génère, ne modifie ou ne valide les mesures numériques.",
    ],
}

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


def _stable_seed(*parts: object) -> int:
    """Return a process-independent seed (unlike Python's randomized hash)."""

    payload = "|".join(str(part) for part in parts).encode("utf-8")
    return int.from_bytes(hashlib.blake2b(payload, digest_size=8).digest(), "big")


def _personal_baseline(patient_id: str, name: str, role: str) -> dict[str, float]:
    """Mirror the database's deterministic healthy-profile derivation.

    The runtime should still inject the persisted database values with
    ``set_baselines``. Keeping the same derivation here gives the sensor source
    a coherent fallback during isolated tests and first-run provisioning.
    """

    identity = f"{BASELINE_PROFILE_VERSION}\0{patient_id}\0{name}\0{role}"
    digest = hashlib.sha256(identity.encode("utf-8")).digest()
    precisions = {"temperature": 2, "spo2": 1, "pulse": 1, "respiration": 1}
    result: dict[str, float] = {}
    for offset, (vital, (low, high)) in enumerate(HEALTHY_BASELINE_RANGES.items()):
        unit = int.from_bytes(digest[offset * 4 : offset * 4 + 4], "big") / 0xFFFFFFFF
        result[vital] = round(low + unit * (high - low), precisions[vital])
    return result


@lru_cache(maxsize=2048)
def _wave_components(seed: int, channel: str) -> tuple[tuple[float, float, float], ...]:
    """Seeded low-frequency components used as continuous sensor residuals."""

    rng = random.Random(_stable_seed(seed, channel, "band-limited-noise"))
    # Incommensurate periods prevent a short, obvious loop during the demo.
    periods = (7.7, 19.3, 47.1, 83.9)
    return tuple(
        (
            period * rng.uniform(0.88, 1.12),
            rng.uniform(0.0, 2.0 * math.pi),
            rng.uniform(0.35, 1.0),
        )
        for period in periods
    )


def _correlated_wave(seed: int, channel: str, now: float) -> float:
    components = _wave_components(seed, channel)
    weighted = sum(
        weight * math.sin((2.0 * math.pi * now / period) + phase)
        for period, phase, weight in components
    )
    normalizer = math.sqrt(sum(weight * weight for _, _, weight in components))
    return weighted / max(1.0, normalizer * 1.6)


@dataclass
class Trajectory:
    """Per-vital transitions, expressed as changes from a personal baseline."""

    targets: dict[str, float] = field(default_factory=dict)
    started_at: float = 0.0
    duration: float = 45.0
    origin: dict[str, float] = field(default_factory=dict)
    delays: dict[str, float] = field(default_factory=dict)
    durations: dict[str, float] = field(default_factory=dict)
    adjustments: dict[str, float] = field(default_factory=dict)
    provenance: str = "healthy-baseline"

    def value(self, key: str, base: float, now: float) -> float:
        if key not in self.targets:
            return base
        delay = max(0.0, self.delays.get(key, 0.0))
        duration = max(0.0, self.durations.get(key, self.duration))
        transition_start = self.started_at + delay
        start = self.origin.get(key, base)
        if now <= transition_start:
            return start
        if duration <= 0:
            return self.targets[key]
        progress = min(1.0, max(0.0, (now - transition_start) / duration))
        # Smoothstep keeps the manually requested endpoints while avoiding an
        # impossible step discontinuity in the displayed sensor signal.
        eased = progress * progress * (3.0 - 2.0 * progress)
        return start + (self.targets[key] - start) * eased

    def to_dict(self) -> dict:
        return {
            "adjustments_from_healthy_baseline": dict(self.adjustments),
            "targets": dict(self.targets),
            "delays_seconds": dict(self.delays),
            "durations_seconds": dict(self.durations),
            "provenance": self.provenance,
        }


@dataclass
class SimPatient:
    id: str
    name: str
    role: str
    seed: int
    baseline: dict[str, float] = field(default_factory=lambda: dict(BASELINE))
    trajectory: Trajectory = field(default_factory=Trajectory)
    contaminated: bool = False
    # A simulated adjustment is not evidence of contagion. This bit is set
    # only by an explicit scenario/operator declaration and is the only
    # simulation state allowed to open the isolation-candidate path.
    exposure_confirmed: bool = False

    def _residual(self, key: str, now: float) -> float:
        # A shared slow component creates modest cross-vital covariance. The
        # oxygen loading is reversed: mild physiological activation generally
        # raises pulse/respiration while oxygen may drift down. Independent
        # channel components retain sensor-specific movement.
        shared_loading = {
            "temperature": 0.20,
            "spo2": -0.35,
            "pulse": 0.55,
            "respiration": 0.45,
        }[key]
        shared = _correlated_wave(self.seed, "physiology", now)
        own = _correlated_wave(self.seed, key, now)
        return NOISE_SCALE[key] * (shared_loading * shared + 0.75 * own)

    def read(self, now: float, *, at: float | None = None) -> Reading:
        v: dict[str, float] = {}
        for key, base in self.baseline.items():
            centre = self.trajectory.value(key, base, now)
            v[key] = centre + self._residual(key, now)

        # These clamps are simulator safety rails, not clinical thresholds.
        v["temperature"] = min(43.0, max(30.0, v["temperature"]))
        v["spo2"] = min(100.0, max(50.0, v["spo2"]))
        v["pulse"] = min(240.0, max(20.0, v["pulse"]))
        v["respiration"] = min(60.0, max(4.0, v["respiration"]))
        return Reading(
            patient_id=self.id,
            at=now if at is None else at,
            temperature=round(v["temperature"], 2),
            spo2=round(v["spo2"], 1),
            pulse=round(v["pulse"], 1),
            respiration=round(v["respiration"], 1),
            # Keep the public source identifier stable; richer provenance is
            # available from ScenarioSource.metadata().
            source="synthetic",
        )


class ScenarioSource:
    """Runs an accelerated, exactly replayable crew simulation."""

    name = "synthetic"

    def __init__(self, crew_size: int, seed: int = 2080) -> None:
        self.seed = seed
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
            # Preserve the original draw order so a given crew seed keeps the
            # same names and roles across simulator versions.
            role = self.rng.choice(ROLES)
            patient_seed = self.rng.randrange(1, 10_000)
            self.patients[pid] = SimPatient(
                id=pid,
                name=name,
                role=role,
                seed=patient_seed,
                baseline=_personal_baseline(pid, name, role),
            )

    def roster(self) -> list[tuple[str, str, str]]:
        """Compatibility roster consumed by the current database layer."""

        return [(p.id, p.name, p.role) for p in self.patients.values()]

    def baseline_records(self) -> list[dict]:
        """Structured seed data for a persistent crew-profile table."""

        return [
            {
                "id": patient.id,
                "name": patient.name,
                "role": patient.role,
                "healthy_baseline": dict(patient.baseline),
                "profile_version": BASELINE_PROFILE_VERSION,
                "simulation_seed": patient.seed,
            }
            for patient in self.patients.values()
        ]

    def metadata(self) -> dict:
        """Return JSON-safe provenance for UI labels, logs and exports."""

        return {
            **PROVENANCE,
            "crew_seed": self.seed,
            "crew_size": len(self.patients),
            "baseline_profile_version": BASELINE_PROFILE_VERSION,
            "active_adjustments": {
                patient.id: patient.trajectory.to_dict()
                for patient in self.patients.values()
                if patient.contaminated
            },
        }

    def set_baselines(self, records: Mapping[str, Mapping[str, float]]) -> None:
        """Load persisted healthy profiles as the simulation source of truth.

        This is intentionally explicit: database values describe each crew
        member's stable reference, while scenario deltas describe operator
        inputs. The two must not be silently blended.
        """

        prepared: dict[str, dict[str, float]] = {}
        for patient_id, values in records.items():
            patient = self.patients.get(patient_id)
            if patient is None:
                continue
            baseline = {vital: float(values[vital]) for vital in VITALS}
            if not all(math.isfinite(value) for value in baseline.values()):
                raise ValueError(f"non-finite healthy baseline for {patient_id}")
            prepared[patient_id] = baseline

        # Apply only after the entire input has validated, so one malformed
        # row cannot leave half the in-memory crew on a new baseline.
        for patient_id, baseline in prepared.items():
            patient = self.patients[patient_id]
            patient.baseline = baseline
            patient.trajectory = Trajectory()
            patient.contaminated = False
            patient.exposure_confirmed = False
        self.t0 = None

    def start(self) -> None:
        self.t0 = None

    def stop(self) -> None:
        pass

    def reset(self) -> None:
        for patient in self.patients.values():
            patient.trajectory = Trajectory()
            patient.contaminated = False
            patient.exposure_confirmed = False
        # Resetting the clock is what makes a replay identical even when it is
        # launched at a different wall-clock time.
        self.t0 = None

    def _elapsed(self, now: float) -> float:
        if self.t0 is None:
            self.t0 = now
        return max(0.0, now - self.t0)

    @staticmethod
    def _mode_for(values: Mapping[str, float]) -> str:
        """Recognise new delta scenarios while retaining legacy absolute calls."""

        plausible_absolute = {
            "temperature": (25.0, 45.0),
            "spo2": (0.0, 100.0),
            "pulse": (20.0, 250.0),
            "respiration": (4.0, 80.0),
        }
        for key, value in values.items():
            low, high = plausible_absolute[key]
            if not low <= float(value) <= high:
                return "delta"
        return "absolute"

    def afflict(
        self,
        patient_ids: list[str],
        targets: dict[str, float],
        over: float,
        now: float,
        *,
        mode: str = "auto",
        delays: Mapping[str, float] | None = None,
        durations: Mapping[str, float] | None = None,
        provenance: str = "scenario-manual-adjustment",
        exposure_confirmed: bool = False,
    ) -> None:
        """Apply a scenario change while preserving the original public API.

        New YAML scenarios provide signed changes from each crew member's own
        baseline. Legacy callers that still provide plausible absolute targets
        continue to work. Ambiguous programmatic calls should pass
        ``mode="delta"`` or use :meth:`apply_deltas` directly.
        """

        clean = {key: float(value) for key, value in targets.items() if key in VITALS}
        if not clean:
            raise ValueError("at least one vital adjustment is required")
        if not all(math.isfinite(value) for value in clean.values()):
            raise ValueError("vital adjustments must be finite")
        selected_mode = self._mode_for(clean) if mode == "auto" else mode
        if selected_mode == "delta":
            self.apply_deltas(
                patient_ids,
                clean,
                over,
                now,
                delays=delays,
                durations=durations,
                provenance=provenance,
                exposure_confirmed=exposure_confirmed,
            )
            return
        if selected_mode != "absolute":
            raise ValueError("mode must be 'auto', 'delta' or 'absolute'")

        elapsed = self._elapsed(now)
        for pid in patient_ids:
            patient = self.patients.get(pid)
            if patient is None:
                continue
            current = patient.read(elapsed, at=now).vitals()
            patient.trajectory = self._trajectory(
                patient,
                clean,
                {
                    key: float(value) - patient.baseline[key]
                    for key, value in clean.items()
                },
                current,
                over,
                elapsed,
                delays,
                durations,
                f"{provenance}:legacy-absolute-target",
            )
            patient.contaminated = True
            patient.exposure_confirmed = patient.exposure_confirmed or bool(exposure_confirmed)

    def apply_deltas(
        self,
        patient_ids: list[str],
        adjustments: Mapping[str, float],
        over: float,
        now: float,
        *,
        delays: Mapping[str, float] | None = None,
        durations: Mapping[str, float] | None = None,
        infer_temperature_associations: bool = True,
        provenance: str = "scenario-manual-adjustment",
        exposure_confirmed: bool = False,
    ) -> None:
        """Apply operator-specified changes from each personal healthy baseline."""

        deltas = {
            key: float(value)
            for key, value in adjustments.items()
            if key in VITALS
        }
        if not deltas:
            raise ValueError("at least one vital adjustment is required")
        if not all(math.isfinite(value) for value in deltas.values()):
            raise ValueError("vital adjustments must be finite")
        if infer_temperature_associations and "temperature" in deltas:
            temp_delta = deltas["temperature"]
            deltas.setdefault("pulse", temp_delta * TEMP_TO_PULSE_BPM_PER_C)
            deltas.setdefault("respiration", temp_delta * TEMP_TO_RESP_PER_MIN_PER_C)

        elapsed = self._elapsed(now)
        for pid in patient_ids:
            patient = self.patients.get(pid)
            if patient is None:
                continue
            # Manual controls may alter one channel at a time. Preserve prior
            # active changes so adjusting SpO2 cannot silently erase a
            # temperature change made one button press earlier.
            combined = (
                dict(patient.trajectory.adjustments)
                if patient.contaminated
                else {}
            )
            combined.update(deltas)
            current = patient.read(elapsed, at=now).vitals()
            targets = {
                key: patient.baseline[key] + delta
                for key, delta in combined.items()
            }
            patient.trajectory = self._trajectory(
                patient,
                targets,
                combined,
                current,
                over,
                elapsed,
                delays,
                durations,
                provenance,
            )
            patient.contaminated = True
            patient.exposure_confirmed = patient.exposure_confirmed or bool(exposure_confirmed)

    @staticmethod
    def _trajectory(
        patient: SimPatient,
        targets: Mapping[str, float],
        adjustments: Mapping[str, float],
        current: Mapping[str, float | None],
        over: float,
        elapsed: float,
        delays: Mapping[str, float] | None,
        durations: Mapping[str, float] | None,
        provenance: str,
    ) -> Trajectory:
        raw_total = float(over)
        if not math.isfinite(raw_total):
            raise ValueError("transition duration must be finite")
        total = max(0.1, raw_total)
        target_keys = tuple(targets)
        delay_values = {
            key: float((delays or {}).get(key, DEFAULT_DELAYS[key]))
            for key in target_keys
        }
        duration_values = {
            key: float((durations or {}).get(key, total * DEFAULT_DURATION_FACTORS[key]))
            for key in target_keys
        }
        if not all(math.isfinite(value) for value in (*delay_values.values(), *duration_values.values())):
            raise ValueError("per-vital timing must be finite")
        return Trajectory(
            targets={key: float(targets[key]) for key in target_keys},
            started_at=elapsed,
            duration=total,
            origin={
                key: float(current[key] if current[key] is not None else patient.baseline[key])
                for key in target_keys
            },
            delays={
                key: max(0.0, delay_values[key])
                for key in target_keys
            },
            durations={
                key: max(0.1, duration_values[key])
                for key in target_keys
            },
            adjustments={key: float(adjustments[key]) for key in target_keys},
            provenance=provenance,
        )

    def healthy_ids(self) -> list[str]:
        return [patient.id for patient in self.patients.values() if not patient.contaminated]

    def sample(self, now: float) -> list[Reading]:
        elapsed = self._elapsed(now)
        return [patient.read(elapsed, at=now) for patient in self.patients.values()]
