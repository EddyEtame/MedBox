"""NEWS2 scoring — the deterministic heart of the fast track.

This is a partial implementation of the National Early Warning Score 2
(Royal College of Physicians, 2017), the scoring system used across the NHS to
decide how urgently a deteriorating patient needs to be seen.

We use a real clinical standard rather than inventing our own scale for three
reasons: it is defensible in front of a jury, it is completely deterministic so
it works with the AI switched off, and every number it produces can be traced
back to the reading that caused it.

NEWS2 has seven parameters. MedBox measures four of them:

    measured   temperature, SpO2, pulse, respiration rate
    assumed    supplemental oxygen (assumed: breathing air)
               consciousness      (assumed: alert)
               systolic BP        (not scored — we have no cuff)

Every result carries the list of parameters that were actually measured, so the
screen can never imply more confidence than the hardware earned.

MEDICAL DISCLAIMER: MedBox is a research and education instrument. It does not
diagnose and it is not a medical device.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

# NEWS2 defines a maximum of 3 points per parameter.
MAX_PARAM_SCORE = 3


class Urgency(str, Enum):
    """NEWS2 clinical risk bands, in the order the board sorts them."""

    ROUTINE = "routine"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

    @property
    def rank(self) -> int:
        return {"routine": 0, "low": 1, "medium": 2, "high": 3}[self.value]

    @property
    def response(self) -> str:
        return {
            "routine": "Routine monitoring, 12-hourly.",
            "low": "Ward-based review by a competent clinician.",
            "medium": "Urgent review. Escalate to the medical officer.",
            "high": "Emergency response. Continuous monitoring.",
        }[self.value]


@dataclass(frozen=True)
class ParamScore:
    """One NEWS2 parameter: what we read, what it scored, and why."""

    name: str
    value: float | None
    score: int
    measured: bool
    reason: str


@dataclass(frozen=True)
class TriageResult:
    total: int
    urgency: Urgency
    params: tuple[ParamScore, ...] = field(default_factory=tuple)

    @property
    def measured_params(self) -> tuple[str, ...]:
        return tuple(p.name for p in self.params if p.measured)

    @property
    def worst_param(self) -> ParamScore | None:
        scored = [p for p in self.params if p.measured]
        return max(scored, key=lambda p: p.score) if scored else None

    @property
    def has_single_param_3(self) -> bool:
        """A single parameter scoring 3 escalates on its own under NEWS2."""
        return any(p.score >= MAX_PARAM_SCORE for p in self.params if p.measured)

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "urgency": self.urgency.value,
            "response": self.urgency.response,
            "measured": list(self.measured_params),
            "params": [
                {
                    "name": p.name,
                    "value": p.value,
                    "score": p.score,
                    "measured": p.measured,
                    "reason": p.reason,
                }
                for p in self.params
            ],
        }


def score_temperature(celsius: float | None) -> ParamScore:
    if celsius is None:
        return ParamScore("temperature", None, 0, False, "no reading")
    if celsius <= 35.0:
        s, why = 3, "hypothermic"
    elif celsius <= 36.0:
        s, why = 1, "below normal"
    elif celsius <= 38.0:
        s, why = 0, "normal"
    elif celsius <= 39.0:
        s, why = 1, "febrile"
    else:
        s, why = 2, "high fever"
    return ParamScore("temperature", round(celsius, 1), s, True, why)


def score_spo2(percent: float | None) -> ParamScore:
    """NEWS2 SpO2 Scale 1 — for patients without hypercapnic respiratory failure."""
    if percent is None:
        return ParamScore("spo2", None, 0, False, "no reading")
    if percent <= 91:
        s, why = 3, "severe hypoxaemia"
    elif percent <= 93:
        s, why = 2, "hypoxaemia"
    elif percent <= 95:
        s, why = 1, "mild desaturation"
    else:
        s, why = 0, "normal"
    return ParamScore("spo2", round(percent, 1), s, True, why)


def score_pulse(bpm: float | None) -> ParamScore:
    if bpm is None:
        return ParamScore("pulse", None, 0, False, "no reading")
    if bpm <= 40:
        s, why = 3, "severe bradycardia"
    elif bpm <= 50:
        s, why = 1, "bradycardia"
    elif bpm <= 90:
        s, why = 0, "normal"
    elif bpm <= 110:
        s, why = 1, "mild tachycardia"
    elif bpm <= 130:
        s, why = 2, "tachycardia"
    else:
        s, why = 3, "severe tachycardia"
    return ParamScore("pulse", round(bpm), s, True, why)


def score_respiration(breaths_per_min: float | None) -> ParamScore:
    if breaths_per_min is None:
        return ParamScore("respiration", None, 0, False, "no reading")
    if breaths_per_min <= 8:
        s, why = 3, "severe bradypnoea"
    elif breaths_per_min <= 11:
        s, why = 1, "bradypnoea"
    elif breaths_per_min <= 20:
        s, why = 0, "normal"
    elif breaths_per_min <= 24:
        s, why = 2, "tachypnoea"
    else:
        s, why = 3, "severe tachypnoea"
    return ParamScore("respiration", round(breaths_per_min), s, True, why)


def score_consciousness(alert: bool = True) -> ParamScore:
    """NEWS2 scores 3 for anything other than Alert on the ACVPU scale."""
    return (
        ParamScore("consciousness", 1, 0, False, "assumed alert")
        if alert
        else ParamScore("consciousness", 0, 3, True, "not alert")
    )


def score_supplemental_oxygen(on_oxygen: bool = False) -> ParamScore:
    return (
        ParamScore("oxygen", 1, 2, True, "on supplemental oxygen")
        if on_oxygen
        else ParamScore("oxygen", 0, 0, False, "assumed breathing air")
    )


def band(total: int, single_param_3: bool) -> Urgency:
    """Map an aggregate NEWS2 score to its clinical risk band.

    The single-parameter rule is the one people forget: a score of 3 in any one
    parameter escalates on its own, even when the aggregate looks reassuring.
    """
    if total >= 7:
        return Urgency.HIGH
    if total >= 5:
        return Urgency.MEDIUM
    if single_param_3:
        return Urgency.MEDIUM
    if total >= 1:
        return Urgency.LOW
    return Urgency.ROUTINE


def assess(
    *,
    temperature: float | None = None,
    spo2: float | None = None,
    pulse: float | None = None,
    respiration: float | None = None,
    alert: bool = True,
    on_oxygen: bool = False,
) -> TriageResult:
    """Score one patient. Pure function: no I/O, no model, no clock."""
    params = (
        score_temperature(temperature),
        score_spo2(spo2),
        score_pulse(pulse),
        score_respiration(respiration),
        score_consciousness(alert),
        score_supplemental_oxygen(on_oxygen),
    )
    total = sum(p.score for p in params)
    single_3 = any(p.score >= MAX_PARAM_SCORE for p in params if p.measured)
    return TriageResult(total=total, urgency=band(total, single_3), params=params)
