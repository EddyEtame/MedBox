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
FULL_NEWS2_PARAMETERS = (
    "temperature",
    "spo2",
    "pulse",
    "respiration",
    "systolic_bp",
    "consciousness",
    "oxygen",
)


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
            "routine": "Surveillance de routine, toutes les 12 heures.",
            "low": "Revue par une personne formée, sans urgence.",
            "medium": "Revue urgente. Prévenir le responsable médical.",
            "high": "Réponse d’urgence. Surveillance continue.",
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
        worst = self.worst_param
        measured = set(self.measured_params)
        missing = [name for name in FULL_NEWS2_PARAMETERS if name not in measured]
        complete = not missing
        return {
            "total": self.total,
            "urgency": self.urgency.value,
            "response": self.urgency.response,
            "measured": list(self.measured_params),
            "complete_news2": complete,
            "missing_news2": missing,
            "score_label": (
                "NEWS2 complet, sept paramètres" if complete
                else f"Dépistage partiel dérivé de NEWS2 — {len(measured)} paramètres sur sept"
            ),
            # Both of these cross into the AI prompt. The single-parameter rule
            # is the thing people forget, and a small model forgets it too: told
            # only "aggregate 3 -> medium" it writes "a low aggregate of 3,
            # overall reassuring" under a MEDIUM band. It has to be given the
            # reason, not just the number.
            "single_param_3": self.has_single_param_3,
            "worst_param": worst.name if worst else None,
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
        s, why = 3, "hypothermie"
    elif celsius <= 36.0:
        s, why = 1, "sous la normale"
    elif celsius <= 38.0:
        s, why = 0, "normale"
    elif celsius <= 39.0:
        s, why = 1, "fièvre"
    else:
        s, why = 2, "forte fièvre"
    return ParamScore("temperature", round(celsius, 1), s, True, why)


def score_spo2(percent: float | None) -> ParamScore:
    """NEWS2 SpO2 Scale 1 — for patients without hypercapnic respiratory failure."""
    if percent is None:
        return ParamScore("spo2", None, 0, False, "no reading")
    if percent <= 91:
        s, why = 3, "hypoxémie sévère"
    elif percent <= 93:
        s, why = 2, "hypoxémie"
    elif percent <= 95:
        s, why = 1, "désaturation légère"
    else:
        s, why = 0, "normale"
    return ParamScore("spo2", round(percent, 1), s, True, why)


def score_pulse(bpm: float | None) -> ParamScore:
    if bpm is None:
        return ParamScore("pulse", None, 0, False, "no reading")
    if bpm <= 40:
        s, why = 3, "bradycardie sévère"
    elif bpm <= 50:
        s, why = 1, "bradycardie"
    elif bpm <= 90:
        s, why = 0, "normal"
    elif bpm <= 110:
        s, why = 1, "tachycardie légère"
    elif bpm <= 130:
        s, why = 2, "tachycardie"
    else:
        s, why = 3, "tachycardie sévère"
    return ParamScore("pulse", round(bpm), s, True, why)


def score_respiration(breaths_per_min: float | None) -> ParamScore:
    if breaths_per_min is None:
        return ParamScore("respiration", None, 0, False, "no reading")
    if breaths_per_min <= 8:
        s, why = 3, "bradypnée sévère"
    elif breaths_per_min <= 11:
        s, why = 1, "bradypnée"
    elif breaths_per_min <= 20:
        s, why = 0, "normale"
    elif breaths_per_min <= 24:
        s, why = 2, "tachypnée"
    else:
        s, why = 3, "tachypnée sévère"
    return ParamScore("respiration", round(breaths_per_min), s, True, why)


def score_systolic_bp(mmhg: float | None) -> ParamScore:
    """NEWS2 systolic blood pressure, RCP 2017: 3 at 90 or below, 2 at 91-100,
    1 at 101-110, 0 at 111-219, 3 at 220 or above."""
    if mmhg is None:
        return ParamScore("systolic_bp", None, 0, False, "aucune mesure")
    if mmhg <= 90:
        s, why = 3, "hypotension sévère"
    elif mmhg <= 100:
        s, why = 2, "hypotension"
    elif mmhg <= 110:
        s, why = 1, "tension basse"
    elif mmhg <= 219:
        s, why = 0, "normale"
    else:
        s, why = 3, "hypertension sévère"
    return ParamScore("systolic_bp", round(mmhg), s, True, why)


# ACVPU, the NEWS2 consciousness scale: Alert scores 0; new Confusion, Voice,
# Pain and Unresponsive all score 3. Entered by the operator, never measured
# by an instrument, and said so.
ACVPU = {
    "A": "alerte",
    "C": "confusion nouvelle",
    "V": "réagit à la voix",
    "P": "réagit à la douleur",
    "U": "sans réaction",
}


def score_consciousness(alert: bool = True, level: str | None = None) -> ParamScore:
    """NEWS2 scores 3 for anything other than Alert on the ACVPU scale.

    With `level` (an ACVPU letter the operator entered) the parameter counts
    as observed; without it, alertness is assumed and the score is a partial
    screen, which the result says.
    """
    if level is not None:
        letter = str(level).strip().upper()[:1]
        if letter not in ACVPU:
            raise ValueError(f"unknown ACVPU level {level!r}")
        if letter == "A":
            return ParamScore("consciousness", 1, 0, True, "alerte (observé)")
        return ParamScore("consciousness", 0, 3, True, ACVPU[letter] + " (observé)")
    return (
        ParamScore("consciousness", 1, 0, False, "vigilance supposée")
        if alert
        else ParamScore("consciousness", 0, 3, True, "non alerte")
    )


def score_supplemental_oxygen(on_oxygen: bool | None = False) -> ParamScore:
    """None: not observed, air assumed. False/True: observed by the operator."""
    if on_oxygen is None:
        return ParamScore("oxygen", 0, 0, False, "air ambiant supposé")
    return (
        ParamScore("oxygen", 1, 2, True, "oxygène supplémentaire")
        if on_oxygen
        else ParamScore("oxygen", 0, 0, True, "air ambiant (observé)")
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
    systolic_bp: float | None = None,
    alert: bool = True,
    consciousness: str | None = None,
    on_oxygen: bool | None = None,
) -> TriageResult:
    """Score one patient. Pure function: no I/O, no model, no clock.

    Seven NEWS2 parameters: five from instruments (the cuff gives systolic
    pressure), two observed by a person (ACVPU, supplemental oxygen). Any that
    is absent is assumed normal and the result says it is a partial screen.
    """
    params = (
        score_temperature(temperature),
        score_spo2(spo2),
        score_pulse(pulse),
        score_respiration(respiration),
        score_systolic_bp(systolic_bp),
        score_consciousness(alert, consciousness),
        score_supplemental_oxygen(on_oxygen),
    )
    total = sum(p.score for p in params)
    single_3 = any(p.score >= MAX_PARAM_SCORE for p in params if p.measured)
    return TriageResult(total=total, urgency=band(total, single_3), params=params)
